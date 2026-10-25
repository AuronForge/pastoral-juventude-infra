"""Generate the provisioned Grafana dashboards.

Usage: python3 scripts/grafana-dashboards.py [--check]
Writes grafana/provisioning/dashboards/{pastoral,endpoints}/*.json; --check only
fails when the committed JSON differs from the generated one (CI).
"""
import json
import sys
from pathlib import Path

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

_id = 0


def nid():
    global _id
    _id += 1
    return _id


def target(expr, legend="", ds=PROM, **extra):
    t = {"datasource": ds, "expr": expr, "refId": chr(64 + extra.pop("ref", 1))}
    if legend:
        t["legendFormat"] = legend
    t.update(extra)
    return t


def thresholds(steps):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}


GREEN_YELLOW_RED = [(None, "green"), (70, "yellow"), (90, "red")]


def stat(title, expr, x, y, w=4, h=4, unit="none", steps=None, decimals=None, mappings=None, legend="", ds=PROM):
    # Loki stats aggregate the whole dashboard range in a single instant query.
    extra = {"queryType": "instant"} if ds is LOKI else {}
    p = {
        "id": nid(), "type": "stat", "title": title, "datasource": ds,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(expr, legend, ds=ds, **extra)],
        "fieldConfig": {"defaults": {"unit": unit, "thresholds": thresholds(steps or [(None, "green")]),
                                     "mappings": mappings or [], "color": {"mode": "thresholds"}},
                        "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background", "graphMode": "area", "textMode": "auto",
                    "justifyMode": "auto", "orientation": "auto"},
    }
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    if ds is LOKI:
        p["fieldConfig"]["defaults"]["noValue"] = "Sem tráfego"
    return p


def gauge(title, expr, x, y, w=4, h=5, unit="percent", steps=GREEN_YELLOW_RED, mx=100):
    return {
        "id": nid(), "type": "gauge", "title": title, "datasource": PROM,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(expr)],
        "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": mx, "thresholds": thresholds(steps),
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "showThresholdLabels": False, "showThresholdMarkers": True},
    }


def ts(title, targets, x, y, w=12, h=8, unit="none", stack=False, mx=None, fill=10, desc="", ds=PROM, bars=False):
    defaults = {
        "unit": unit, "color": {"mode": "palette-classic"},
        "custom": {"drawStyle": "bars" if bars else "line", "lineWidth": 1, "fillOpacity": fill, "showPoints": "never",
                   "spanNulls": True, "stacking": {"mode": "normal" if stack else "none", "group": "A"}},
    }
    if mx is not None:
        defaults["max"] = mx
        defaults["min"] = 0
    p = {
        "id": nid(), "type": "timeseries", "title": title, "datasource": ds,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(e, l, ds=ds, ref=i + 1) for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull", "max"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }
    if desc:
        p["description"] = desc
    return p


def dash_links(tag, title):
    return {"type": "dashboards", "tags": [tag], "asDropdown": True,
            "title": title, "includeVars": False, "keepTime": True}


def row(title, y):
    return {"id": nid(), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def dashboard(uid, title, panels, tags, templating=None, refresh="30s", time_from="now-6h", links=None):
    return {
        "uid": uid, "title": title, "tags": ["pastoral"] + tags, "timezone": "browser",
        "schemaVersion": 39, "version": 1, "editable": True, "graphTooltip": 1,
        "refresh": refresh, "time": {"from": time_from, "to": "now"},
        "templating": {"list": templating or []}, "annotations": {"list": []},
        "panels": panels, "links": links or [dash_links("pastoral", "Dashboards")],
    }


UP_MAP = [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"},
                                        "1": {"text": "UP", "color": "green"}}}]
UP_STEPS = [(None, "red"), (1, "green")]


# --- Servidor ---------------------------------------------------------------
def host():
    global _id
    _id = 0
    n = 'job="node"'
    cpu = f'100 * (1 - avg(rate(node_cpu_seconds_total{{{n},mode="idle"}}[$__rate_interval])))'
    mem = f'100 * (1 - node_memory_MemAvailable_bytes{{{n}}} / node_memory_MemTotal_bytes{{{n}}})'
    swap = f'100 * (1 - node_memory_SwapFree_bytes{{{n}}} / node_memory_SwapTotal_bytes{{{n}}})'
    fs = f'fstype!~"tmpfs|overlay|squashfs|ramfs|fuse.*",mountpoint!~"/boot.*|/snap.*"'
    disk = f'100 * (1 - node_filesystem_avail_bytes{{{n},mountpoint="/"}} / node_filesystem_size_bytes{{{n},mountpoint="/"}})'
    temp = f'max(node_hwmon_temp_celsius{{{n}}})'
    load_ratio = f'node_load1{{{n}}} / scalar(count(node_cpu_seconds_total{{{n},mode="idle"}}))'
    p = [
        stat("Status", f'up{{{n}}}', 0, 0, w=3, mappings=UP_MAP, steps=UP_STEPS),
        stat("Ligado há", f'time() - node_boot_time_seconds{{{n}}}', 3, 0, w=3, unit="s", decimals=1),
        gauge("CPU", cpu, 6, 0, w=3, h=4),
        gauge("RAM", mem, 9, 0, w=3, h=4),
        gauge("Swap", swap, 12, 0, w=3, h=4),
        gauge("Disco /", disk, 15, 0, w=3, h=4, steps=[(None, "green"), (80, "yellow"), (90, "red")]),
        gauge("Temperatura", temp, 18, 0, w=3, h=4, unit="celsius",
              steps=[(None, "green"), (75, "yellow"), (85, "red")], mx=100),
        stat("Carga / núcleo", load_ratio, 21, 0, w=3, unit="percentunit", decimals=2,
             steps=[(None, "green"), (1, "yellow"), (2, "red")]),
        row("CPU e memória", 4),
        ts("CPU por modo", [(f'100 * avg by (mode) (rate(node_cpu_seconds_total{{{n},mode!="idle"}}[$__rate_interval]))', "{{mode}}")],
           0, 5, unit="percent", stack=True, mx=100),
        ts("Carga do sistema", [(f'node_load1{{{n}}}', "1 min"), (f'node_load5{{{n}}}', "5 min"),
                                (f'node_load15{{{n}}}', "15 min"),
                                (f'count(node_cpu_seconds_total{{{n},mode="idle"}})', "núcleos")],
           12, 5, fill=0),
        ts("Memória", [(f'node_memory_MemTotal_bytes{{{n}}} - node_memory_MemAvailable_bytes{{{n}}}', "usada"),
                       (f'node_memory_Buffers_bytes{{{n}}} + node_memory_Cached_bytes{{{n}}}', "buffers/cache"),
                       (f'node_memory_MemAvailable_bytes{{{n}}}', "disponível"),
                       (f'node_memory_SwapTotal_bytes{{{n}}} - node_memory_SwapFree_bytes{{{n}}}', "swap usado")],
           0, 13, unit="bytes"),
        ts("Pressão (PSI) — tempo esperando recurso", [
            (f'rate(node_pressure_cpu_waiting_seconds_total{{{n}}}[$__rate_interval]) * 100', "CPU"),
            (f'rate(node_pressure_memory_waiting_seconds_total{{{n}}}[$__rate_interval]) * 100', "memória"),
            (f'rate(node_pressure_io_waiting_seconds_total{{{n}}}[$__rate_interval]) * 100', "I/O")],
           12, 13, unit="percent", fill=0,
           desc="Porcentagem do tempo em que tarefas ficaram esperando CPU, memória ou disco."),
        row("Disco, rede e temperatura", 21),
        ts("Uso dos sistemas de arquivos", [(f'100 * (1 - node_filesystem_avail_bytes{{{n},{fs}}} / node_filesystem_size_bytes{{{n},{fs}}})', "{{mountpoint}}")],
           0, 22, w=8, unit="percent", mx=100, fill=0),
        ts("I/O de disco", [(f'rate(node_disk_read_bytes_total{{{n},device!~"loop.*|ram.*"}}[$__rate_interval])', "leitura {{device}}"),
                            (f'rate(node_disk_written_bytes_total{{{n},device!~"loop.*|ram.*"}}[$__rate_interval])', "escrita {{device}}")],
           8, 22, w=8, unit="Bps", fill=0),
        ts("Rede", [(f'rate(node_network_receive_bytes_total{{{n},device!~"lo|veth.*|br-.*|docker.*"}}[$__rate_interval])', "recebe {{device}}"),
                    (f'rate(node_network_transmit_bytes_total{{{n},device!~"lo|veth.*|br-.*|docker.*"}}[$__rate_interval])', "envia {{device}}")],
           16, 22, w=8, unit="Bps", fill=0),
        ts("Temperatura", [(f'node_hwmon_temp_celsius{{{n}}}', "{{chip}} {{sensor}}")], 0, 30, w=24, h=7,
           unit="celsius", fill=0),
    ]
    return dashboard("pastoral-host", "Servidor (host)", p, ["host"])


# --- Containers -------------------------------------------------------------
def containers():
    global _id
    _id = 0
    c = 'job="cadvisor",name=~"$container"'
    var = {
        "name": "container", "label": "Container", "type": "query", "datasource": PROM,
        "query": {"query": 'label_values(container_last_seen{job="cadvisor",name!=""}, name)', "refId": "q"},
        "definition": 'label_values(container_last_seen{job="cadvisor",name!=""}, name)',
        "refresh": 2, "includeAll": True, "multi": True, "allValue": ".+",
        "current": {"text": "All", "value": "$__all"}, "sort": 1,
    }
    p = [
        stat("Containers rodando", f'count(container_last_seen{{{c}}} > time() - 60)', 0, 0, w=6),
        stat("CPU total (núcleos)", f'sum(rate(container_cpu_usage_seconds_total{{{c}}}[$__rate_interval]))', 6, 0, w=6, decimals=2),
        stat("Memória total", f'sum(container_memory_working_set_bytes{{{c}}})', 12, 0, w=6, unit="bytes"),
        stat("Memória da VM / daemon", f'machine_memory_bytes{{job="cadvisor"}}', 18, 0, w=6, unit="bytes"),
        ts("CPU por container", [(f'sum by (name) (rate(container_cpu_usage_seconds_total{{{c}}}[$__rate_interval])) * 100', "{{name}}")],
           0, 4, unit="percent", desc="100% = um núcleo inteiro."),
        ts("Memória por container (working set)", [(f'sum by (name) (container_memory_working_set_bytes{{{c}}})', "{{name}}")],
           12, 4, unit="bytes"),
        ts("Uso do limite de memória", [(f'100 * sum by (name) (container_memory_working_set_bytes{{{c}}}) / sum by (name) (container_spec_memory_limit_bytes{{{c}}} > 0)', "{{name}}")],
           0, 12, unit="percent", mx=100, fill=0, desc="Somente containers com mem_limit."),
        ts("CPU limitada (throttling)", [(f'sum by (name) (rate(container_cpu_cfs_throttled_seconds_total{{{c}}}[$__rate_interval]))', "{{name}}")],
           12, 12, unit="s", fill=0),
        ts("Rede recebida", [(f'sum by (name) (rate(container_network_receive_bytes_total{{{c}}}[$__rate_interval]))', "{{name}}")],
           0, 20, unit="Bps", fill=0),
        ts("Rede enviada", [(f'sum by (name) (rate(container_network_transmit_bytes_total{{{c}}}[$__rate_interval]))', "{{name}}")],
           12, 20, unit="Bps", fill=0),
        ts("Eventos OOM (falta de memória)", [(f'sum by (name) (increase(container_oom_events_total{{{c}}}[$__rate_interval]))', "{{name}}")],
           0, 28, w=24, h=6, fill=0),
    ]
    return dashboard("pastoral-containers", "Containers", p, ["containers"], [var])


# --- Pastoral ---------------------------------------------------------------
def services():
    global _id
    _id = 0
    t = 'job="traefik"'
    b = 'job="backend"'
    up = lambda job: f'up{{job="{job}"}}'
    p = [
        stat("Backend", up("backend"), 0, 0, w=3, mappings=UP_MAP, steps=UP_STEPS),
        stat("Traefik", up("traefik"), 3, 0, w=3, mappings=UP_MAP, steps=UP_STEPS),
        stat("PostgreSQL", 'pg_up{job="postgres"}', 6, 0, w=3, mappings=UP_MAP, steps=UP_STEPS),
        stat("Redis", 'redis_up{job="redis"}', 9, 0, w=3, mappings=UP_MAP, steps=UP_STEPS),
        stat("Requisições/s", f'sum(rate(traefik_service_requests_total{{{t}}}[$__rate_interval]))', 12, 0, w=4, unit="reqps", decimals=2),
        stat("Erros 5xx", f'100 * (sum(rate(traefik_service_requests_total{{{t},code=~"5.."}}[$__rate_interval])) or vector(0)) / clamp_min(sum(rate(traefik_service_requests_total{{{t}}}[$__rate_interval])), 1e-9)',
             16, 0, w=4, unit="percent", decimals=2, steps=[(None, "green"), (1, "yellow"), (5, "red")]),
        stat("Latência p95", f'histogram_quantile(0.95, sum by (le) (rate(traefik_service_request_duration_seconds_bucket{{{t}}}[$__rate_interval])))',
             20, 0, w=4, unit="s", decimals=3, steps=[(None, "green"), (0.5, "yellow"), (1, "red")]),
        row("Tráfego (Traefik)", 4),
        ts("Requisições por serviço", [(f'sum by (service) (rate(traefik_service_requests_total{{{t}}}[$__rate_interval]))', "{{service}}")],
           0, 5, unit="reqps"),
        ts("Respostas por código", [(f'sum by (code) (rate(traefik_service_requests_total{{{t}}}[$__rate_interval]))', "{{code}}")],
           12, 5, unit="reqps", stack=True),
        ts("Latência por serviço (p50 / p95)", [
            (f'histogram_quantile(0.5, sum by (le, service) (rate(traefik_service_request_duration_seconds_bucket{{{t}}}[$__rate_interval])))', "p50 {{service}}"),
            (f'histogram_quantile(0.95, sum by (le, service) (rate(traefik_service_request_duration_seconds_bucket{{{t}}}[$__rate_interval])))', "p95 {{service}}")],
           0, 13, unit="s", fill=0),
        ts("Servidores saudáveis no Traefik", [(f'traefik_service_server_up{{{t}}}', "{{service}} {{url}}")],
           12, 13, mx=1, fill=0),
        row("Backend (Node.js)", 21),
        ts("Memória do processo", [(f'pastoral_backend_process_resident_memory_bytes{{{b}}}', "RSS"),
                                   (f'pastoral_backend_nodejs_heap_size_used_bytes{{{b}}}', "heap usado"),
                                   (f'pastoral_backend_nodejs_heap_size_total_bytes{{{b}}}', "heap total")],
           0, 22, w=8, unit="bytes", fill=0),
        ts("Event loop lag", [(f'pastoral_backend_nodejs_eventloop_lag_p50_seconds{{{b}}}', "p50"),
                              (f'pastoral_backend_nodejs_eventloop_lag_p99_seconds{{{b}}}', "p99")],
           8, 22, w=8, unit="s", fill=0),
        ts("CPU do processo", [(f'rate(pastoral_backend_process_cpu_seconds_total{{{b}}}[$__rate_interval]) * 100', "CPU")],
           16, 22, w=8, unit="percent", fill=0),
        row("PostgreSQL", 30),
        ts("Conexões por estado", [('sum by (state) (pg_stat_activity_count{job="postgres"})', "{{state}}")],
           0, 31, w=8, stack=True),
        ts("Transações/s", [('sum(rate(pg_stat_database_xact_commit{job="postgres"}[$__rate_interval]))', "commit"),
                            ('sum(rate(pg_stat_database_xact_rollback{job="postgres"}[$__rate_interval]))', "rollback")],
           8, 31, w=8, fill=0),
        ts("Tamanho do banco", [('pg_database_size_bytes{job="postgres",datname!~"template.*|postgres"}', "{{datname}}")],
           16, 31, w=8, unit="bytes", fill=0),
        row("Redis", 39),
        ts("Memória usada", [('redis_memory_used_bytes{job="redis"}', "usada"),
                             ('redis_memory_max_bytes{job="redis"} > 0', "limite")],
           0, 40, w=8, unit="bytes", fill=0),
        ts("Comandos/s", [('rate(redis_commands_processed_total{job="redis"}[$__rate_interval])', "comandos")],
           8, 40, w=8, unit="ops", fill=0),
        ts("Clientes e chaves", [('redis_connected_clients{job="redis"}', "clientes"),
                                 ('sum(redis_db_keys{job="redis"})', "chaves")],
           16, 40, w=8, fill=0),
    ]
    return dashboard("pastoral-services", "Pastoral — Serviços", p, ["app"])


# --- Logs -------------------------------------------------------------------
def logs():
    global _id
    _id = 0
    sel = '{service=~"$service"} |~ "(?i)$search"'
    var_service = {
        "name": "service", "label": "Serviço", "type": "query", "datasource": LOKI,
        "query": {"label": "service", "refId": "LokiVariableQueryEditor-VariableQuery", "stream": "", "type": 1},
        "definition": "label_values(service)", "refresh": 2, "includeAll": True, "multi": True,
        "allValue": ".+", "current": {"text": "All", "value": "$__all"}, "sort": 1,
    }
    var_search = {"name": "search", "label": "Buscar", "type": "textbox", "query": "",
                  "current": {"text": "", "value": ""}}
    p = [
        {"id": nid(), "type": "timeseries", "title": "Volume de logs por serviço", "datasource": LOKI,
         "gridPos": {"x": 0, "y": 0, "w": 12, "h": 7},
         "targets": [target(f'sum by (service) (count_over_time({sel} [$__auto]))', "{{service}}", ds=LOKI)],
         "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"},
                                      "custom": {"drawStyle": "bars", "fillOpacity": 60, "stacking": {"mode": "normal", "group": "A"}}},
                         "overrides": []},
         "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}},
        {"id": nid(), "type": "timeseries", "title": "Erros e avisos", "datasource": LOKI,
         "gridPos": {"x": 12, "y": 0, "w": 12, "h": 7},
         "targets": [target(f'sum by (service, level) (count_over_time({{service=~"$service",level=~"(?i)error|fatal|warn.*|40|50|60"}} [$__auto]))',
                            "{{service}} {{level}}", ds=LOKI),
                     target(f'sum by (service) (count_over_time({{service=~"$service"}} |~ "(?i)\\\\b(error|exception|fatal)\\\\b" [$__auto]))',
                            "{{service}} (texto)", ds=LOKI, ref=2)],
         "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"},
                                      "custom": {"drawStyle": "bars", "fillOpacity": 60, "stacking": {"mode": "normal", "group": "A"}}},
                         "overrides": []},
         "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
         "description": "Nível warn/error/fatal (texto ou pino 40/50/60) ou linhas que mencionam error/exception/fatal."},
        {"id": nid(), "type": "logs", "title": "Logs", "datasource": LOKI,
         "gridPos": {"x": 0, "y": 7, "w": 24, "h": 20},
         "targets": [target(sel, ds=LOKI)],
         "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                     "enableLogDetails": True, "prettifyLogMessage": False, "dedupStrategy": "none"}},
    ]
    return dashboard("pastoral-logs", "Logs", p, ["logs"], [var_service, var_search], refresh="1m", time_from="now-1h")




# --- Endpoints (Traefik JSON access log in Loki) -----------------------------
# One dashboard per route exposed by traefik/dynamic*.yml. Add new API routes here.
# (slug, declared method, path or None for the whole router, Traefik router, application log selector:
#  None searches the backend log for the path; False omits the panel)
ENDPOINTS = [
    # health-report serves a static report and logs no requests.
    ("health", "GET", "/api/v1/health", "backend-public-health-v1@file", False),
    ("login", "POST", "/api/v1/autenticacao/login", "backend-api-v1@file", None),
    ("logout", "POST", "/api/v1/autenticacao/logout", "backend-api-v1@file", None),
    ("renovar-token", "POST", "/api/v1/autenticacao/renovar-token", "backend-api-v1@file", None),
    ("recuperar-senha", "POST", "/api/v1/autenticacao/recuperar-senha", "backend-api-v1@file", None),
    ("alterar-senha", "POST", "/api/v1/autenticacao/alterar-senha", "backend-api-v1@file", None),
    ("frontend", "GET", None, "frontend@file", '{service="frontend"}'),
]

ACCESS = ('{service="traefik"} | json RouterName, RequestMethod, RequestPath, DownstreamStatus, '
          'Duration, DownstreamContentSize')
ACCESS_LINE = '{{.DownstreamStatus}} {{.RequestMethod}} {{.RequestPath}} {{ div .Duration 1000000 }} ms'
ENDPOINT_LINKS = [dash_links("endpoint", "Endpoints"), dash_links("pastoral", "Dashboards")]
STATUS_STEPS = [(None, "green"), (1, "yellow"), (5, "red")]


def access(router, path=None, extra=""):
    sel = f'{ACCESS} | RouterName=`{router}`'
    if path:
        # Traefik logs the original path, including any query string.
        sel += f' | RequestPath=~`{path}(\\?.*)?`'
    return sel + extra


def ratio(sel, status):
    return (f'100 * (sum(count_over_time({sel} | DownstreamStatus=~`{status}` [$__range])) or vector(0))'
            f' / sum(count_over_time({sel} [$__range]))')


def logs_panel(title, expr, x, y, w=24, h=10):
    return {"id": nid(), "type": "logs", "title": title, "datasource": LOKI,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": [target(expr, ds=LOKI)],
            "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                        "enableLogDetails": True, "prettifyLogMessage": False, "dedupStrategy": "none"}}


def table(title, expr, x, y, w=24, h=8, rename=None):
    return {"id": nid(), "type": "table", "title": title, "datasource": LOKI,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [target(expr, ds=LOKI, queryType="instant")],
            "transformations": [{"id": "labelsToFields", "options": {"mode": "columns"}},
                                {"id": "organize", "options": {"excludeByName": {"Time": True},
                                                               "renameByName": rename or {}}}],
            "fieldConfig": {"defaults": {}, "overrides": []},
            "options": {"showHeader": True, "sortBy": [{"displayName": "Requisições", "desc": True}]}}


def endpoint(slug, method, path, router, app_logs):
    global _id
    _id = 0
    sel = access(router, path)
    title = f"{method} {path}" if path else f"Frontend ({router.split('@')[0]})"
    q = lambda fn, extra="": f'{fn}({sel}{extra} [$__auto])'
    p = [
        stat("Requisições", f'sum(count_over_time({sel} [$__range]))', 0, 0, ds=LOKI),
        stat("Média por minuto", f'sum(count_over_time({sel} [$__range])) / ($__range_s / 60)', 4, 0,
             decimals=2, ds=LOKI),
        stat("Sucesso (2xx/3xx)", ratio(sel, "[23].."), 8, 0, unit="percent", decimals=1, ds=LOKI,
             steps=[(None, "red"), (90, "yellow"), (99, "green")]),
        stat("Erros 4xx", ratio(sel, "4.."), 12, 0, unit="percent", decimals=1, ds=LOKI, steps=STATUS_STEPS),
        stat("Erros 5xx", ratio(sel, "5.."), 16, 0, unit="percent", decimals=1, ds=LOKI, steps=STATUS_STEPS),
        stat("Latência p95", f'quantile_over_time(0.95, {sel} | unwrap Duration [$__range]) by ()', 20, 0,
             unit="ns", ds=LOKI, steps=[(None, "green"), (500e6, "yellow"), (1e9, "red")]),
        ts("Requisições por status", [(f'sum by (DownstreamStatus) ({q("count_over_time")})', "{{DownstreamStatus}}")],
           0, 4, ds=LOKI, stack=True, bars=True, fill=60),
        ts("Latência", [(f'quantile_over_time({v}, {sel} | unwrap Duration [$__auto]) by ()', f"p{int(v * 100)}")
                        for v in (0.5, 0.95, 0.99)], 12, 4, unit="ns", ds=LOKI, fill=0),
        ts("Requisições por método", [(f'sum by (RequestMethod) ({q("count_over_time")})', "{{RequestMethod}}")],
           0, 12, w=8, ds=LOKI, stack=True, bars=True, fill=60,
           desc=f"Método declarado: {method}. Outros métodos indicam chamadas incorretas."),
        ts("Erros", [(f'sum({q("count_over_time", " | DownstreamStatus=~`4..`")})', "4xx"),
                     (f'sum({q("count_over_time", " | DownstreamStatus=~`5..`")})', "5xx")],
           8, 12, w=8, ds=LOKI, bars=True, fill=60),
        ts("Tamanho médio da resposta", [(f'avg_over_time({sel} | unwrap DownstreamContentSize [$__auto]) by ()', "bytes")],
           16, 12, w=8, unit="bytes", ds=LOKI, fill=0),
    ]
    y = 20
    if not path:
        p.append(table("Caminhos mais acessados",
                       f'topk(20, sum by (RequestPath) (count_over_time({sel} [$__range])))', 0, y,
                       rename={"RequestPath": "Caminho", "Value": "Requisições"}))
        y += 8
    p.append(logs_panel("Acessos (Traefik)", f'{sel} | line_format "{ACCESS_LINE}"', 0, y))
    if app_logs is not False:
        app = app_logs or f'{{service="backend"}} |= `{path}`'
        p.append(logs_panel("Logs da aplicação", app, 0, y + 10))
    return dashboard(f"pastoral-endpoint-{slug}", f"Endpoint — {title}", p, ["endpoint"],
                     refresh="1m", links=ENDPOINT_LINKS)


def endpoints_overview():
    global _id
    _id = 0
    api = access("backend-.*")
    api = api.replace("RouterName=`backend-.*`", "RouterName=~`backend-.*`")
    p = [
        {"id": nid(), "type": "dashlist", "title": "Dashboards por endpoint",
         "gridPos": {"x": 0, "y": 0, "w": 6, "h": 10},
         "options": {"showSearch": True, "showHeadings": False, "showStarred": False, "showRecentlyViewed": False,
                     "query": "", "tags": ["endpoint"], "maxItems": 20, "includeVars": False, "keepTime": True}},
        table("Requisições da API por caminho e status",
              f'sum by (RequestMethod, RequestPath, DownstreamStatus) (count_over_time({api} [$__range]))', 6, 0,
              w=18, h=10, rename={"RequestMethod": "Método", "RequestPath": "Caminho",
                                  "DownstreamStatus": "Status", "Value": "Requisições"}),
        ts("Requisições da API por caminho",
           [(f'sum by (RequestPath) (count_over_time({api} [$__auto]))', "{{RequestPath}}")], 0, 10,
           ds=LOKI, stack=True, bars=True, fill=60),
        ts("Latência p95 da API por caminho",
           [(f'quantile_over_time(0.95, {api} | unwrap Duration [$__auto]) by (RequestPath)', "{{RequestPath}}")],
           12, 10, unit="ns", ds=LOKI, fill=0),
        ts("Erros 4xx/5xx por caminho",
           [(f'sum by (RequestPath, DownstreamStatus) (count_over_time({api} | DownstreamStatus=~`[45]..` [$__auto]))',
             "{{DownstreamStatus}} {{RequestPath}}")], 0, 18, ds=LOKI, stack=True, bars=True, fill=60),
        ts("Requisições por roteador",
           [(f'sum by (RouterName) (count_over_time({ACCESS} | RouterName!=`` [$__auto]))', "{{RouterName}}")],
           12, 18, ds=LOKI, stack=True, bars=True, fill=60),
    ]
    return dashboard("pastoral-endpoints", "Endpoints — visão geral", p, ["endpoint"], refresh="1m",
                     links=ENDPOINT_LINKS)


def generate():
    return {
        "pastoral": {"host": host(), "containers": containers(), "services": services(), "logs": logs()},
        "endpoints": {"overview": endpoints_overview(),
                      **{slug: endpoint(slug, *rest) for slug, *rest in ENDPOINTS}},
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent / "grafana/provisioning/dashboards"
    check = sys.argv[1:] == ["--check"]
    stale = []
    for folder, dashboards in generate().items():
        (root / folder).mkdir(parents=True, exist_ok=True)
        for name, data in dashboards.items():
            path = root / folder / f"{name}.json"
            text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            if check:
                if not path.exists() or path.read_text() != text:
                    stale.append(str(path.relative_to(root)))
            else:
                path.write_text(text)
    if stale:
        sys.exit("Dashboards out of date; run python3 scripts/grafana-dashboards.py: " + ", ".join(stale))
