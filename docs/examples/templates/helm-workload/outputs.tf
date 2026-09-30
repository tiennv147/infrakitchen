output "release_name" {
  value = helm_release.this.name
}

output "namespace" {
  value = helm_release.this.namespace
}

output "revision" {
  value = helm_release.this.metadata[0].revision
}

output "status" {
  value = helm_release.this.status
}

output "chart_version" {
  value = helm_release.this.version
}

output "image_tag" {
  value = var.image_tag
}
