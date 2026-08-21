{{- define "agentbarn-api.selectorLabels" -}}
app.kubernetes.io/name: agentbarn-api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "agentbarn-api.labels" -}}
{{ include "agentbarn-api.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}
