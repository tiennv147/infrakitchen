{{- define "ik-app.name" -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}{{- end -}}

{{- define "ik-app.selector" -}}
app.kubernetes.io/name: {{ include "ik-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "ik-app.labels" -}}
{{ include "ik-app.selector" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default "latest" | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}
