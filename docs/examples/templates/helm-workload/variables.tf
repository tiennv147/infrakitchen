variable "release_name" {
  type        = string
  description = "Helm release name"
}

variable "namespace" {
  type        = string
  description = "Namespace of the release; it must already exist"
}

variable "chart" {
  type        = string
  description = "Chart reference, e.g. oci://registry.example.com/charts/app"
}

variable "chart_version" {
  type        = string
  description = "Pinned chart version"
}

variable "values" {
  type        = list(string)
  default     = []
  description = "Values file contents, applied in order (base, environment, region)"
}

variable "values_commit" {
  type        = string
  default     = null
  description = "Commit the values files were read from; recorded for traceability"
}

variable "image_tag_key" {
  type        = string
  default     = "image.tag"
  description = "Chart value set to image_tag"
}

variable "image_tag" {
  type        = string
  default     = null
  description = "Version to deploy; the chart default is used when null"
}

variable "atomic" {
  type    = bool
  default = true
}

variable "wait" {
  type    = bool
  default = true
}

variable "timeout" {
  type    = number
  default = 300
}

variable "cleanup_on_fail" {
  type    = bool
  default = true
}

variable "cluster_name" {
  type        = string
  description = "EKS cluster the release is applied to"
}

variable "region" {
  type        = string
  description = "AWS region of the cluster"
}

variable "environment_name" {
  type        = string
  default     = null
  description = "InfraKitchen environment; used for naming only"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Accepted for consistency with other templates; Helm releases are not tagged"
}
