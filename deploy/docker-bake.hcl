# One build graph for every Stitch image (deploy design 2, 4). Run from the repository root:
#   docker buildx bake -f deploy/docker-bake.hcl                     # core images, local tag
#   TAG=<sha> GH_OWNER=<owner> docker buildx bake -f deploy/docker-bake.hcl --push all
#   docker buildx bake -f deploy/docker-bake.hcl placeholder         # dry-run gateway only
# CI adds the GitHub Actions layer cache with --set '*.cache-from=type=gha' and
# --set '*.cache-to=type=gha,mode=max'. Image names match compose.yaml.

variable "REGISTRY" { default = "ghcr.io" }
variable "GH_OWNER" { default = "stitch-local" }
variable "TAG" { default = "local" }
variable "SOURCE_URL" { default = "" }
variable "STITCH_MODELS_CONTEXT" { default = "deploy/docker/empty" }

function "img" {
  params = [name]
  result = ["${REGISTRY}/${GH_OWNER}/stitch-${name}:${TAG}"]
}

group "default" {
  targets = ["ledger", "oracle", "library", "brain", "web"]
}

group "all" {
  targets = ["ledger", "oracle", "library", "brain", "eyes", "web"]
}

target "_python" {
  context    = "."
  dockerfile = "deploy/docker/python.Dockerfile"
  target     = "runtime"
  args       = { SOURCE_URL = "${SOURCE_URL}" }
  labels     = { "org.opencontainers.image.revision" = "${TAG}" }
}

target "ledger" {
  inherits = ["_python"]
  args     = { PACKAGE = "stitch-ledger", SRC_DIR = "organs/ledger" }
  tags     = img("ledger")
}

target "oracle" {
  inherits = ["_python"]
  args     = { PACKAGE = "stitch-oracle", SRC_DIR = "organs/oracle" }
  tags     = img("oracle")
}

target "eyes" {
  inherits = ["_python"]
  args     = { PACKAGE = "stitch-eyes", SRC_DIR = "organs/eyes" }
  tags     = img("eyes")
}

target "brain" {
  inherits = ["_python"]
  args     = { PACKAGE = "stitch-brain", SRC_DIR = "brain" }
  tags     = img("brain")
}

target "library" {
  inherits = ["_python"]
  target   = "library"
  args     = { PACKAGE = "stitch-library", SRC_DIR = "organs/library" }
  contexts = { localmodels = "${STITCH_MODELS_CONTEXT}" }
  tags     = img("library")
}

target "web" {
  context    = "."
  dockerfile = "deploy/docker/web.Dockerfile"
  labels     = { "org.opencontainers.image.revision" = "${TAG}" }
  tags       = img("web")
}

target "placeholder" {
  context    = "."
  dockerfile = "deploy/docker/web.placeholder.Dockerfile"
  tags       = img("web")
}
