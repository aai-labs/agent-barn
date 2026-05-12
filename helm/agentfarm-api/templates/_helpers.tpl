{{- define "agentfarm-api.selectorLabels" -}}
app.kubernetes.io/name: agentfarm-api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "agentfarm-api.labels" -}}
{{ include "agentfarm-api.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}
