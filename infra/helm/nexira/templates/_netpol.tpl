{{/* Egress rules shared by the network policies (networkpolicies.yaml). */}}
{{- define "nexira.egress.dns" -}}
{{- if not .Values.networkPolicy.dns.namespaceSelector }}{{ fail "networkPolicy.dns.namespaceSelector is required (the cluster DNS namespace)" }}{{ end -}}
- to:
    - namespaceSelector: {{ toYaml .Values.networkPolicy.dns.namespaceSelector | nindent 8 }}
      podSelector: {{ toYaml .Values.networkPolicy.dns.podSelector | nindent 8 }}
  ports:
    - { protocol: UDP, port: 53 }
    - { protocol: TCP, port: 53 }
    - { protocol: UDP, port: 5353 }
    - { protocol: TCP, port: 5353 }
{{- end -}}
{{- define "nexira.egress.db" -}}
{{- $peers := include "nexira.peers" .Values.database.egress -}}
{{- if not $peers }}{{ fail "database.egress needs ipBlocks or selectors (where PostgreSQL is)" }}{{ end -}}
- to: {{- $peers | nindent 4 }}
  ports:
    - { protocol: TCP, port: {{ .Values.database.port }} }
{{- end -}}
{{- define "nexira.egress.redis" -}}
{{- if .Values.redis.enabled }}
- to:
    - podSelector:
        matchLabels: {{- include "nexira.selector" (list . "redis") | nindent 10 }}
  ports:
    - { protocol: TCP, port: 6379 }
{{- else }}
{{- $peers := include "nexira.peers" .Values.redis.egress -}}
{{- if not $peers }}{{ fail "redis.egress needs ipBlocks or selectors when redis.enabled is false" }}{{ end }}
- to: {{- $peers | nindent 4 }}
  ports:
    - { protocol: TCP, port: {{ .Values.redis.egress.port }} }
{{- end }}
{{- end -}}
{{- define "nexira.egress.llm" -}}
{{- if ne .Values.llm.provider "stub" }}
{{- $peers := include "nexira.peers" .Values.llm.egress -}}
{{- if not $peers }}{{ fail "llm.egress needs ipBlocks or selectors when llm.provider is not stub" }}{{ end }}
- to: {{- $peers | nindent 4 }}
  ports:
  {{- range .Values.llm.egress.ports }}
    - { protocol: TCP, port: {{ . }} }
  {{- end }}
{{- end }}
{{- end -}}
