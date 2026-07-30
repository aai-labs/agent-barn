{{- define "firecrawl.selectorLabels" -}}
app.kubernetes.io/name: firecrawl
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "firecrawl.labels" -}}
{{ include "firecrawl.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}
