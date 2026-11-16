// Friendly aliases over the generated contract namespaces (src/gen/contracts.ts).
// Nothing here is hand-written contract: change the Pydantic models, then `npm run gen:types`.
import type {
  BrainBriefing,
  BrainTaskEvent,
  BrainApiOrganList,
  BrainApiBriefingAccepted,
  BrainApiBriefingRequest,
  BrainApiBriefingState,
  BrainApiEvidenceValue,
  BrainApiPayloadPlan,
  BrainApiPayloadOrganCall,
  BrainApiPayloadOrganResult,
  BrainApiPayloadCritic,
  BrainApiPayloadError,
  BrainApiPayloadNotice,
  BrainApiAskResponse,
  BrainApiSpeakRequest,
  BrainApiVoiceSpeakResponse,
  BrainApiVoiceTranscribeResponse,
  CommonToolResult,
  CommonProvenance,
  OracleForecastRiverOut,
  LedgerOptimizeAllocationOut,
  LedgerSensitivityReportOut,
  LedgerResourceDistricts,
  EyesSegmentFloodOut,
  EyesCompareWithPermanentWaterOut,
  LibraryAnswerWithCitationsOut,
} from '@/gen/contracts';

export type Briefing = BrainBriefing.Briefing;
export type Section = BrainBriefing.Section;
export type Claim = BrainBriefing.Claim;
export type Conflict = BrainBriefing.Conflict;
export type EvidenceRef = BrainBriefing.EvidenceRef;
export type CriticVerdict = BrainBriefing.CriticVerdict;
export type TaskEvent = BrainTaskEvent.TaskEvent;
export type TaskEventType = BrainTaskEvent.Event;

export type OrganList = BrainApiOrganList.OrganList;
export type OrganInfo = BrainApiOrganList.OrganInfo;
export type BriefingAccepted = BrainApiBriefingAccepted.BriefingAccepted;
export type BriefingRequest = BrainApiBriefingRequest.BriefingRequest;
export type BriefingState = BrainApiBriefingState.BriefingState;
export type EvidenceValue = BrainApiEvidenceValue.EvidenceValue;
export type PlanPayload = BrainApiPayloadPlan.PlanPayload;
export type OrganCallPayload = BrainApiPayloadOrganCall.OrganCallPayload;
export type OrganResultPayload = BrainApiPayloadOrganResult.OrganResultPayload;
export type CriticPayload = BrainApiPayloadCritic.CriticPayload;
export type ErrorPayload = BrainApiPayloadError.ErrorPayload;
export type NoticePayload = BrainApiPayloadNotice.NoticePayload;
export type AskResponse = BrainApiAskResponse.AskResponse;
export type SpeakRequest = BrainApiSpeakRequest.SpeakRequest;
export type VoiceSpeakResponse = BrainApiVoiceSpeakResponse.VoiceSpeakResponse;
export type VoiceTranscribeResponse = BrainApiVoiceTranscribeResponse.VoiceTranscribeResponse;

export type Provenance = CommonProvenance.Provenance;
export type ToolError = CommonToolResult.ErrorInfo;
export interface ToolEnvelope<T> {
  ok: boolean;
  data: T | null;
  error: ToolError | null;
  provenance: Provenance;
  warnings?: string[];
}
export type ForecastOut = OracleForecastRiverOut.ForecastRiverOut;
export type OptimizeOut = LedgerOptimizeAllocationOut.OptimizeAllocationOut;
export type SensitivityOut = LedgerSensitivityReportOut.SensitivityReportOut;
export type TradeoffPoint = LedgerSensitivityReportOut.TradeoffPoint;
export type ScenarioDistrict = LedgerResourceDistricts.ScenarioDistrict;
export type SegmentOut = EyesSegmentFloodOut.SegmentFloodOut;
export type CompareOut = EyesCompareWithPermanentWaterOut.CompareWithPermanentWaterOut;
export type DistrictFlood = EyesCompareWithPermanentWaterOut.DistrictFlood;
export type AnswerOut = LibraryAnswerWithCitationsOut.AnswerWithCitationsOut;
export type Citation = LibraryAnswerWithCitationsOut.Citation;

export type OrganId = 'eyes' | 'oracle' | 'library' | 'ledger' | 'voice';
export const ORGAN_IDS: readonly OrganId[] = ['eyes', 'oracle', 'library', 'ledger', 'voice'] as const;
export type Lang = 'en' | 'ur';
export type Mode = 'demo' | 'live';

export type ApiErrorCode = 'RATE_LIMITED' | 'UNREACHABLE' | 'TIMEOUT' | 'NOT_FOUND' | 'INVALID_INPUT' | 'UPSTREAM_UNAVAILABLE' | 'BUSY' | 'INTERNAL';
export interface ApiError {
  code: ApiErrorCode;
  message: string;
  status?: number;
  retryAfterS?: number;
}
export type Result<T, E = ApiError> = { ok: true; value: T } | { ok: false; error: E };