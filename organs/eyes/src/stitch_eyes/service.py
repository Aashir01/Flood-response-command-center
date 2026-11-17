"""Eyes tool cores (design 10, 11): input checks, scene lookup, pipeline, envelope details.

Cores return ``Outcome`` objects (data, warnings, data sources, model) and raise
``ToolFailure`` for the error table of design 11. No network: every input is under
``data/demo``. A ``live`` request falls back to the demo scene with a ``MODE_FALLBACK`` warning.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import date
from typing import Any, get_args

from stitch_common.organs.eyes import (
    CompareWithPermanentWaterIn,
    CompareWithPermanentWaterOut,
    DistrictFlood,
    ModelVariant,
    SceneInfo,
    SegmentFloodIn,
    SegmentFloodOut,
    SourceScene,
    Validation,
)
from stitch_common.provenance import DataSource, ModelInfo
from stitch_common.tooling import Outcome, ToolFailure
from stitch_eyes.core.districts import District, aggregate
from stitch_eyes.core.grid import valid_tile_size
from stitch_eyes.core.infer import (
    ModelIntegrityError,
    OnnxTileModel,
    ThresholdTileModel,
    TileModel,
)
from stitch_eyes.core.vectorize import vectorize
from stitch_eyes.data.scene import (
    Catalog,
    Scene,
    SceneNotFound,
    Window,
    WindowError,
    full_window,
    load_districts,
    load_overlay,
    window_for_bbox,
)
from stitch_eyes.pipeline import NoValidData, ResultCache, SegResult, segment
from stitch_eyes.settings import Settings

EVAL_DATASET = "sen1floods11_test"
MODEL_VERSION = "0.1.0"
NOTE_MODEL = (
    "Demo scene: Sindh, Aug 2022. The model was fine-tuned and validated on the Sen1Floods11 "
    "test split only. Sen1Floods11 has no Sindh 2022 event, so this output is not a validated "
    "result for this region."
)
NOTE_THRESHOLD = (
    "Demo scene: Sindh, Aug 2022. This output comes from a VH threshold baseline, not the "
    "trained network. The baseline was evaluated on the Sen1Floods11 test split only, so this "
    "output is not a validated result for this region."
)
NOTE_VALIDATED = "Scene inside the evaluation domain."
DEMO_WARNING = (
    "DEMO: demo scene (Sindh, Aug 2022), not validated for this region; the model is "
    "validated on the Sen1Floods11 test split only"
)
MODE_FALLBACK_WARNING = (
    "MODE_FALLBACK: live mode was requested, but the Eyes have no live scene source; "
    "they used the committed demo scene"
)
NO_FLOOD_WARNING = "no flood pixels, confidence undefined (null)"
NO_OVERLAY_NOTE = (
    "No reference extent is committed for this scene, so there is no overlay "
    "(scripts/fetch_reference_extent.py builds one from a redistributable source)."
)
ALLOWED_VARIANTS: frozenset[str] = frozenset(get_args(ModelVariant))

SEN1FLOODS11 = DataSource(
    id="sen1floods11-v1.1",
    name="Sen1Floods11 hand-labeled (training and evaluation data of the model)",
    license="CC-BY-4.0",
    as_of=None,
)
JRC_GSW = DataSource(
    id="jrc-gsw-v1.4-occurrence",
    name="JRC Global Surface Water v1.4 occurrence 1984-2021 (Pekel et al. 2016), "
    "Source: EC JRC/Google",
    license="Copernicus programme: free of charge, without restriction of use",
    as_of=date(2021, 12, 31),
)
BOUNDARIES = DataSource(
    id="geoboundaries-pak-adm2",
    name="geoBoundaries gbOpen PAK ADM2 (simplified, Sindh)",
    license="CC-BY-4.0",
    as_of=None,
)


def check_request(bbox: tuple[float, float, float, float] | None, tile_size: int) -> None:
    """Checks beyond the contract model (design 11): a non-empty bbox and a valid tile size."""
    if bbox is not None:
        w, s, e, n = bbox
        if not (w < e and s < n):
            raise ToolFailure("INVALID_INPUT", "bbox requires west < east and south < north")
    if not valid_tile_size(tile_size):
        raise ToolFailure("INVALID_INPUT", "tile_size must be a power of two in 64..1024")


class EyesService:
    def __init__(self, settings: Settings | None = None, model: TileModel | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._model = model
        self._model_error: str | None = None
        self._catalog: Catalog | None = None
        self._districts: list[District] | None = None
        self._lock = threading.Lock()
        self.cache = ResultCache(self.settings.cache_size)

    # ---- resources -------------------------------------------------------------------------
    def catalog(self) -> Catalog:
        with self._lock:
            if self._catalog is None:
                try:
                    self._catalog = Catalog(self.settings.eyes_dir)
                except (OSError, ValueError, KeyError) as exc:
                    raise ToolFailure("INTERNAL", f"scene catalog unavailable: {exc}") from None
            return self._catalog

    def districts(self) -> list[District]:
        with self._lock:
            if self._districts is None:
                try:
                    self._districts = load_districts(self.settings.boundaries)
                except (OSError, ValueError, KeyError) as exc:
                    raise ToolFailure(
                        "INTERNAL", f"district boundaries unavailable: {exc}"
                    ) from None
            return self._districts

    def model(self) -> TileModel:
        with self._lock:
            if self._model is not None:
                return self._model
            if self._model_error is not None:
                raise ToolFailure("INTERNAL", self._model_error)
            try:
                self._model = self._load_model()
            except (ModelIntegrityError, OSError, ValueError, KeyError) as exc:
                self._model_error = f"model unavailable: {exc}"
                raise ToolFailure("INTERNAL", self._model_error) from None
            return self._model

    def _load_model(self) -> TileModel:
        if self.settings.model_choice == "threshold":
            return ThresholdTileModel()
        d = self.settings.model_dir
        check = json.loads((d / "export_check.json").read_text(encoding="utf-8"))
        return OnnxTileModel(
            d / check["file"],
            expected_sha256=check["sha256"],
            variant=check["model_variant"],
            version=MODEL_VERSION,
            threads=self.settings.threads,
        )

    def scenes(self) -> list[SceneInfo]:
        return [
            SceneInfo(
                region_id=s.region_id,
                date=s.date,
                scene_id=s.scene_id,
                sensor=s.sensor,
                validated_for_region=s.validated_region,
            )
            for s in self.catalog().scenes
        ]

    def health(self) -> dict[str, bool]:
        checks: dict[str, bool] = {}
        for name, fn in (
            ("model", self.model),
            ("catalog", self.catalog),
            ("boundaries", self.districts),
        ):
            try:
                fn()
                checks[name] = True
            except ToolFailure:
                checks[name] = False
        return checks

    def cores(self) -> dict[str, Callable[[Any], Any]]:
        return {
            "segment_flood": self.segment_flood,
            "compare_with_permanent_water": self.compare_with_permanent_water,
        }

    # ---- shared steps ----------------------------------------------------------------------
    def _resolve(
        self,
        region_id: str,
        when: date,
        bbox: tuple[float, float, float, float] | None,
        tile_size: int,
        mode: str | None,
    ) -> tuple[SegResult, list[str]]:
        warnings: list[str] = []
        if mode == "live":
            warnings.append(MODE_FALLBACK_WARNING)
        check_request(bbox, tile_size)
        try:
            scene, days = self.catalog().find(region_id, when, self.settings.date_tolerance_days)
        except SceneNotFound as exc:
            raise ToolFailure("NOT_FOUND", str(exc)) from None
        if days:
            warnings.append(
                f"SCENE_DATE: no scene on {when.isoformat()}; the nearest scene, acquired "
                f"{scene.date.isoformat()} ({days} day(s) away, within the "
                f"{self.settings.date_tolerance_days}-day tolerance), was used"
            )
        try:
            win = (
                full_window(scene)
                if bbox is None
                else window_for_bbox(scene, bbox, self.settings.max_area_km2)
            )
        except WindowError as exc:
            code = "NOT_FOUND" if exc.kind == "not_found" else "INVALID_INPUT"
            raise ToolFailure(code, str(exc)) from None
        if bbox is None:
            area = scene.shape[0] * scene.shape[1] * scene.res**2 / 1e6
            if area > self.settings.max_area_km2:
                raise ToolFailure("INVALID_INPUT", "scene exceeds the maximum window area")
        res = self._segment(scene, win, tile_size)
        if not scene.validated_region:
            warnings.append(DEMO_WARNING)
        if res.valid_fraction < 0.99:
            warnings.append(
                f"valid data covers {res.valid_fraction:.1%} of the window; nodata pixels are "
                "treated as not water"
            )
        warnings.append(
            "Permanent water: JRC GSW occurrence >= 50% (30 m), dilated by "
            f"{self.settings.perm_dilate_px} px ({self.settings.perm_dilate_px * scene.res:.0f} "
            "m); new flood next to permanent water may be hidden"
        )
        return res, warnings

    def _segment(self, scene: Scene, win: Window, tile_size: int) -> SegResult:
        model = self.model()
        districts = self.districts()
        key = (scene.sha256, model.sha256, tile_size, win.key, self.settings.perm_dilate_px)

        def compute() -> SegResult:
            return segment(scene, win, tile_size, model, districts, self.settings.perm_dilate_px)

        try:
            res, _hit = self.cache.get_or_compute(key, compute)
        except NoValidData:
            raise ToolFailure("NOT_FOUND", "no valid data in the requested window") from None
        return res

    def warm(self) -> None:
        """Compute the default demo-scene result once (startup warm-up); errors are ignored."""
        try:
            for scene in self.catalog().scenes:
                self._segment(scene, full_window(scene), 256)
        except ToolFailure:
            pass

    def _sources(self, scene: Scene) -> list[DataSource]:
        return [
            DataSource(
                id=scene.scene_id,
                name=f"Sentinel-1 scene {scene.scene_id} ({scene.source_name}). "
                f"{scene.attribution}",
                license=scene.license,
                as_of=scene.date,
            ),
            JRC_GSW,
            SEN1FLOODS11,
            BOUNDARIES,
        ]

    def _model_info(self) -> tuple[ModelInfo, str | None, bool]:
        m = self.model()
        variant = m.variant if m.variant in ALLOWED_VARIANTS else None
        return (
            ModelInfo(name=m.name, version=m.version, sha256=m.sha256),
            variant,
            m.variant == "vh-threshold-baseline",
        )

    # ---- tools -----------------------------------------------------------------------------
    def segment_flood(self, params: SegmentFloodIn) -> Outcome[SegmentFloodOut]:
        res, warnings = self._resolve(
            params.region_id, params.date, params.bbox, params.tile_size, params.mode
        )
        info, variant, is_baseline = self._model_info()
        if variant is None:
            warnings.append(f"model variant '{self.model().variant}' has no contract label")
        s = self.settings
        vec = vectorize(
            res.split.new_flood,
            res.prob,
            res.confidence,
            res.window.transform(res.scene),
            res.scene.crs,
            res.col_area_m2,
            low_conf_threshold=s.low_conf_threshold,
            min_polygon_km2=s.min_polygon_km2,
            simplify_m=s.simplify_m,
            max_features=s.max_features,
        )
        warnings.extend(vec.warnings)
        conf = res.flood_confidence
        if conf is None:
            warnings.append(NO_FLOOD_WARNING)
        overlay, overlay_note = load_overlay(s.eyes_dir, res.scene.region_id)
        scene = res.scene
        validation = Validation(
            validated_for_region=scene.validated_region,
            eval_dataset=EVAL_DATASET,
            note=(NOTE_THRESHOLD if is_baseline else NOTE_MODEL)
            if not scene.validated_region
            else NOTE_VALIDATED,
        )
        out = SegmentFloodOut(
            flood_extent_km2=round(res.split.new_flood_km2, 6),
            extent_geojson=vec.feature_collection,  # type: ignore[arg-type]
            permanent_water_km2=round(res.split.permanent_water_km2, 6),
            confidence=None if conf is None else round(conf, 6),
            tiles_processed=res.tiles_processed,
            source_scene=SourceScene(
                sensor=scene.sensor, acquired=scene.acquired, scene_id=scene.scene_id
            ),
            validation=validation,
            reference_overlay_geojson=overlay,  # type: ignore[arg-type]
            reference_overlay_note=overlay_note if overlay is not None else NO_OVERLAY_NOTE,
            valid_fraction=round(res.valid_fraction, 6),
            model_variant=variant,  # type: ignore[arg-type]
        )
        return Outcome(
            out, warnings=warnings, data_sources=self._sources(scene), model=info, mode="demo"
        )

    def compare_with_permanent_water(
        self, params: CompareWithPermanentWaterIn
    ) -> Outcome[CompareWithPermanentWaterOut]:
        res, warnings = self._resolve(params.region_id, params.date, params.bbox, 256, params.mode)
        info, _variant, _ = self._model_info()
        stats = aggregate(res.district_index, res.districts, res.split.new_flood, res.col_area_m2)
        out = CompareWithPermanentWaterOut(
            total_water_km2=round(res.split.total_water_km2, 6),
            permanent_water_km2=round(res.split.permanent_water_km2, 6),
            new_flood_km2=round(res.split.new_flood_km2, 6),
            by_district=[
                DistrictFlood(
                    district_id=st.district_id,
                    name=st.name,
                    flooded_km2=round(st.flooded_km2, 6),
                    flooded_fraction=round(st.flooded_fraction, 6),
                    district_area_km2=round(st.district_area_km2, 6),
                )
                for st in stats
            ],
        )
        warnings.append(
            "by_district covers only the part of each district inside the scene window "
            "(district_area_km2); flooded_roads_km is not computed by the Eyes"
        )
        return Outcome(
            out, warnings=warnings, data_sources=self._sources(res.scene), model=info, mode="demo"
        )
