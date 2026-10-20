// m5perf: log wrapper — records errors during interaction probes
window.__m5log = [];
window.addEventListener('error', e => window.__m5log.push({type:'error', msg: String(e.message)}));
window.addEventListener('unhandledrejection', e => window.__m5log.push({type:'rejection', msg: String(e.reason)}));
'm5log installed';
