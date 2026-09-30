provider "aws" {
  region = var.region
}

data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

data "aws_eks_cluster_auth" "this" {
  name = var.cluster_name
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}

# atomic/wait/timeout/cleanup_on_fail match `helm upgrade --install --atomic --wait`, so a failed rollout rolls back.
resource "helm_release" "this" {
  name             = var.release_name
  namespace        = var.namespace
  create_namespace = false
  chart            = var.chart
  version          = var.chart_version
  values           = var.values

  atomic          = var.atomic
  wait            = var.wait
  timeout         = var.timeout
  cleanup_on_fail = var.cleanup_on_fail

  dynamic "set" {
    for_each = var.image_tag == null ? [] : [var.image_tag]
    content {
      name  = var.image_tag_key
      value = set.value
      type  = "string"
    }
  }
}
