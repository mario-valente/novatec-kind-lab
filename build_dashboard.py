import json
from pathlib import Path

DATASOURCE = {"type": "prometheus", "uid": "lab-prometheus"}
GROUP = "cluster, source, target"
SCOPE = 'cluster=~"${cluster:regex}",tenant=~"${tenant:regex}"'
FILTER = SCOPE + ',journey=~"${journey:regex}"'
MEMBERSHIP = (
    f"max by ({GROUP}) (max_over_time(lab_edge_last_seen_seconds{{{FILTER}}}[$__range]))"
    " >= (${__from} / 1000)"
)


def expressions(strict):
    selector = FILTER if strict else SCOPE
    all_calls = f"sum by ({GROUP}) (rate(lab_calls_total{{{selector}}}[$__rate_interval]))"
    ok = f'sum by ({GROUP}) (rate(lab_calls_total{{{selector},status="ok"}}[$__rate_interval]))'
    err = f'sum by ({GROUP}) (rate(lab_calls_total{{{selector},status="error"}}[$__rate_interval]))'
    latency = (
        f"1000 * sum by ({GROUP}) (rate(lab_call_duration_seconds_sum{{{selector}}}[$__rate_interval]))"
        f" / sum by ({GROUP}) (rate(lab_call_duration_seconds_count{{{selector}}}[$__rate_interval]))"
    )
    return [
        f"({ok} or on ({GROUP}) (0 * {all_calls})) and on ({GROUP}) ({MEMBERSHIP})",
        f"({latency}) and on ({GROUP}) ({MEMBERSHIP})",
        f"({err} or on ({GROUP}) (0 * {all_calls})) and on ({GROUP}) ({MEMBERSHIP})",
    ]


def targets(strict):
    return [
        {"refId": ref, "expr": expr, "instant": True, "range": False, "format": "table", "datasource": DATASOURCE}
        for ref, expr in zip(("A", "B", "C"), expressions(strict))
    ]


OPTIONS = {
    "animate": True,
    "sumTimings": False,
    "filterEmptyConnections": True,
    "showConnectionStats": True,
    "showDebugInformation": False,
    "showBaselines": False,
    "timeFormat": "m",
    "drillDownLink": "",
    "icons": [{"pattern": "redis", "filename": "database"}],
    "externalIcons": [],
    "style": {
        "healthyColor": "rgb(87, 148, 242)",
        "dangerColor": "rgb(196, 22, 42)",
        "noDataColor": "rgb(123, 123, 138)",
    },
    "dataMapping": {
        "aggregationType": "target",
        "sourceColumn": "source",
        "targetColumn": "unused_target",
        "namespaceColumn": "unused_namespace",
        "namespaceDelimiter": ".",
        "responseTimeColumn": "Value #B",
        "requestRateColumn": "Value #A",
        "errorRateColumn": "Value #C",
        "responseTimeOutgoingColumn": "Value #B",
        "requestRateOutgoingColumn": "Value #A",
        "errorRateOutgoingColumn": "Value #C",
        "extOrigin": "unused_external_origin",
        "extTarget": "unused_external_target",
        "type": "unused_type",
        "baselineRtUpper": "unused_threshold",
        "showDummyData": False,
    },
}


def graph(panel_id, strict, x):
    return {
        "id": panel_id,
        "title": "1. Metricas DA jornada" if strict else "2. Componentes da jornada / metricas GLOBAIS",
        "description": (
            "Origem/destino e metricas filtrados por journey e tenant. Latencia media client-side em ms."
            if strict else
            "Filtra as arestas pela jornada; valores agregam TODAS as jornadas do tenant selecionado. Nao atribuir esses tempos exclusivamente a jornada."
        ),
        "type": "novatec-sdg-panel",
        "pluginVersion": "4.2.0",
        "datasource": DATASOURCE,
        "gridPos": {"x": x, "y": 4, "w": 12, "h": 13},
        "options": OPTIONS,
        "fieldConfig": {"defaults": {}, "overrides": []},
        "targets": targets(strict),
    }


def table(panel_id, strict, x):
    return {
        "id": panel_id,
        "title": "Dados: jornada" if strict else "Dados: agregados entre jornadas",
        "type": "table",
        "datasource": DATASOURCE,
        "gridPos": {"x": x, "y": 17, "w": 12, "h": 7},
        "targets": targets(strict),
        "transformations": [
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "cluster": True},
                "renameByName": {"Value #A": "Sucessos/s", "Value #B": "Latencia media (ms)", "Value #C": "Erros/s"},
            }},
        ],
        "fieldConfig": {"defaults": {"decimals": 2, "custom": {"width": 110}}, "overrides": []},
        "options": {"showHeader": True},
    }


dashboard = {
    "uid": "novatec-journeys",
    "title": "Novatec - fluxos por jornada e tenant",
    "schemaVersion": 39,
    "version": 1,
    "editable": False,
    "tags": ["lab", "novatec", "journey"],
    "timezone": "browser",
    "refresh": "5s",
    "time": {"from": "now-15m", "to": "now"},
    "templating": {"list": [
        {"name": "cluster", "label": "Cluster", "type": "constant", "query": "novatec-lab", "hide": 2,
         "current": {"text": "novatec-lab", "value": "novatec-lab"}},
        {"name": "journey", "label": "Jornada", "type": "custom",
         "query": "Entrada normal de WhatsApp : whatsapp_inbound, Notificacao ativa : active_notification",
         "includeAll": True, "allValue": ".*", "multi": False,
         "current": {"text": "Entrada normal de WhatsApp", "value": "whatsapp_inbound"},
         "options": [
             {"text": "All", "value": "$__all", "selected": False},
             {"text": "Entrada normal de WhatsApp", "value": "whatsapp_inbound", "selected": True},
             {"text": "Notificacao ativa", "value": "active_notification", "selected": False},
         ]},
        {"name": "tenant", "label": "Tenant (filtro, nao autorizacao)", "type": "custom",
         "query": "tenant-a,tenant-b", "includeAll": True, "allValue": ".*", "multi": False,
         "current": {"text": "tenant-a", "value": "tenant-a"},
         "options": [
             {"text": "All", "value": "$__all", "selected": False},
             {"text": "tenant-a", "value": "tenant-a", "selected": True},
             {"text": "tenant-b", "value": "tenant-b", "selected": False},
         ]},
    ]},
    "panels": [
        {"id": 1, "type": "text", "title": "Como testar", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 4},
         "options": {"mode": "markdown", "content": (
             "**Troque Jornada acima.** WhatsApp: `app-a -> app-b -> redis`. "
             "Notificacao ativa: `app-a -> app-b` (Redis deve desaparecer).\n\n"
             "**Esquerda:** metricas exclusivas da jornada. **Direita:** so a topologia e filtrada; "
             "a aresta compartilhada agrega metricas de todas as jornadas. "
             "Clique nas arestas para os detalhes. Latencia media em ms; sem eBPF, sem dados ficticios do plugin."
         )}},
        graph(2, True, 0),
        graph(3, False, 12),
        table(4, True, 0),
        table(5, False, 12),
    ],
}

if __name__ == "__main__":
    output = Path(__file__).parent / "generated"
    output.mkdir(exist_ok=True)
    (output / "journeys.json").write_text(json.dumps(dashboard, indent=2) + "\n")
