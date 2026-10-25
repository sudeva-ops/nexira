{{- define "nexira.fullname" -}}
{{- if contains "nexira" .Release.Name -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-nexira" .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "nexira.labels" -}}
app.kubernetes.io/name: nexira
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Selector labels for one component: include "nexira.selector" (list . "backend") */}}
{{- define "nexira.selector" -}}
app.kubernetes.io/name: nexira
app.kubernetes.io/instance: {{ (index . 0).Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end -}}

{{- define "nexira.image" -}}
{{- $root := index . 0 -}}{{- $image := index . 1 -}}
{{- if $root.Values.imageRegistry -}}
{{- printf "%s/%s:%s" $root.Values.imageRegistry $image.repository $image.tag -}}
{{- else -}}
{{- printf "%s:%s" $image.repository $image.tag -}}
{{- end -}}
{{- end -}}

{{- define "nexira.secret" -}}
{{- $root := index . 0 -}}{{- $which := index . 1 -}}
{{- if $root.Values.secrets.create -}}
{{- printf "%s-%s" (include "nexira.fullname" $root) $which -}}
{{- else -}}
{{- index $root.Values.secrets.existing $which -}}
{{- end -}}
{{- end -}}

{{/* Restricted Pod Security Standard; OpenShift picks the UID/fsGroup itself. */}}
{{- define "nexira.podSecurityContext" -}}
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- if not .Values.openshift }}
fsGroup: 10001
{{- end }}
{{- end -}}

{{- define "nexira.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/* Pod spec fields shared by every workload. */}}
{{- define "nexira.podCommon" -}}
serviceAccountName: {{ include "nexira.fullname" . }}
automountServiceAccountToken: false
{{- with .Values.imagePullSecrets }}
imagePullSecrets: {{ toYaml . | nindent 2 }}
{{- end }}
securityContext: {{ include "nexira.podSecurityContext" . | nindent 2 }}
{{- end -}}

{{/* A NetworkPolicy egress peer list from {ipBlocks, namespaceSelector, podSelector}. */}}
{{- define "nexira.peers" -}}
{{- range .ipBlocks }}
- ipBlock: { cidr: {{ . | quote }} }
{{- end }}
{{- if or .namespaceSelector .podSelector }}
- {{- with .namespaceSelector }}
  namespaceSelector: {{ toYaml . | nindent 4 }}
  {{- end }}
  {{- with .podSelector }}
  podSelector: {{ toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
{{- end -}}
