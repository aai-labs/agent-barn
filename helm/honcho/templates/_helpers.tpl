{{- define "honcho.selectorLabels" -}}
app.kubernetes.io/name: honcho
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "honcho.labels" -}}
{{ include "honcho.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "honcho.apiSelectorLabels" -}}
{{ include "honcho.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{- define "honcho.deriverSelectorLabels" -}}
{{ include "honcho.selectorLabels" . }}
app.kubernetes.io/component: deriver
{{- end }}
