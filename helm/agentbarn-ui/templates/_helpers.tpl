{{- define "agentbarn-ui.selectorLabels" -}}
app.kubernetes.io/name: agentbarn-ui
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "agentbarn-ui.labels" -}}
{{ include "agentbarn-ui.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}
