{{- define "agentbarn-api.selectorLabels" -}}
app.kubernetes.io/name: agentbarn-api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "agentbarn-api.labels" -}}
{{ include "agentbarn-api.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
What every process that starts or trims restore point Jobs needs: the API deployment,
the reconciliation CronJob and the scheduled snapshot CronJob. The schedule interval is
always rendered, since 0 (schedule off) is a value an `if` would drop.
*/}}
{{- define "agentbarn-api.restorePointEnv" -}}
{{- if .Values.storageClass }}
- name: STORAGE_CLASS
  value: "{{ .Values.storageClass }}"
{{- end }}
- name: AGENT_IMAGE_PULL_SECRET
  value: "{{ .Values.agentImagePullSecret }}"
- name: API_IMAGE
  value: "{{ .Values.registryPrefix }}/{{ .Values.image.repository }}:{{ required "image.tag is required" .Values.image.tag }}"
{{- if .Values.restorePoints.size }}
- name: RESTORE_POINT_SIZE
  value: "{{ .Values.restorePoints.size }}"
{{- end }}
{{- if .Values.restorePoints.maxPerAgent }}
- name: RESTORE_POINT_MAX_PER_AGENT
  value: "{{ .Values.restorePoints.maxPerAgent }}"
{{- end }}
{{- if .Values.restorePoints.captureTimeoutSeconds }}
- name: RESTORE_POINT_CAPTURE_TIMEOUT_SECONDS
  value: "{{ .Values.restorePoints.captureTimeoutSeconds }}"
{{- end }}
{{- if .Values.restorePoints.restoreTimeoutSeconds }}
- name: RESTORE_POINT_RESTORE_TIMEOUT_SECONDS
  value: "{{ .Values.restorePoints.restoreTimeoutSeconds }}"
{{- end }}
- name: RESTORE_POINT_SCHEDULE_INTERVAL_MINUTES
  value: {{ .Values.restorePoints.schedule.intervalMinutes | quote }}
{{- if .Values.restorePoints.schedule.maxPerAgent }}
- name: RESTORE_POINT_SCHEDULED_MAX_PER_AGENT
  value: "{{ .Values.restorePoints.schedule.maxPerAgent }}"
{{- end }}
{{- if .Values.restorePoints.schedule.maxConcurrent }}
- name: RESTORE_POINT_SCHEDULE_MAX_CONCURRENT
  value: "{{ .Values.restorePoints.schedule.maxConcurrent }}"
{{- end }}
{{- end }}
