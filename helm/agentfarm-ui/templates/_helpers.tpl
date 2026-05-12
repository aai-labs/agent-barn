{{- define "agentfarm-ui.selectorLabels" -}}
app.kubernetes.io/name: agentfarm-ui
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "agentfarm-ui.labels" -}}
{{ include "agentfarm-ui.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}
