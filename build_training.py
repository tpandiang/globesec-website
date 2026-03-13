"""Build training.html for GlobeSec.ai with AWS SCS-C03 study guide content."""
import os
import re

STUDY_DIR = r"C:\Users\txp190010\Downloads\AWS-SCS-C03-Study-Docs"
OUTPUT = r"C:\Users\txp190010\Downloads\globesec\training.html"

FILES = [
    ("Domain1-Threat-Detection-Incident-Response.md", "Threat Detection & IR", "16%"),
    ("Domain2-Security-Logging-Monitoring.md", "Logging & Monitoring", "14%"),
    ("Domain3-Infrastructure-Security.md", "Infrastructure Security", "18%"),
    ("Domain4-Identity-Access-Management.md", "Identity & Access Mgmt", "20%"),
    ("Domain5-Data-Protection.md", "Data Protection", "18%"),
    ("Domain6-Management-Security-Governance.md", "Governance", "14%"),
    ("Study-Plan.md", "Study Plan", ""),
]


def md_to_html(md_text, domain_num):
    """Convert markdown text to HTML."""
    lines = md_text.split('\n')
    html = []
    i = 0
    section_count = 0

    def inline_fmt(text):
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)
        return text

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # H1
        if stripped.startswith('# '):
            i += 1
            continue

        # H2
        if stripped.startswith('## '):
            title = stripped[3:].strip()
            if title.startswith('CHEATSHEET'):
                section_count += 1
                sid = "d{}-cheatsheet".format(domain_num)
                html.append('<div class="section cheatsheet-section" id="{}">'.format(sid))
                html.append('<h2 class="section-title cheatsheet-title" onclick="toggleSection(this)">'
                           '<span class="toggle-icon">&#9654;</span> {}</h2>'.format(inline_fmt(title)))
                html.append('<div class="section-body" style="display:none;">')
            else:
                if section_count > 0:
                    html.append('</div></div>')
                section_count += 1
                sid = "d{}-s{}".format(domain_num, section_count)
                html.append('<div class="section" id="{}">'.format(sid))
                html.append('<h2 class="section-title" onclick="toggleSection(this)">'
                           '<span class="toggle-icon">&#9660;</span> {}</h2>'.format(inline_fmt(title)))
                html.append('<div class="section-body">')
            i += 1
            continue

        # H3
        if stripped.startswith('### '):
            title = stripped[4:].strip()
            html.append('<h3>{}</h3>'.format(inline_fmt(title)))
            i += 1
            continue

        # H4
        if stripped.startswith('#### '):
            title = stripped[5:].strip()
            html.append('<h4>{}</h4>'.format(inline_fmt(title)))
            i += 1
            continue

        # HR
        if stripped in ('---', '***', '___'):
            i += 1
            continue

        # Table
        if stripped.startswith('|') and '|' in stripped[1:]:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                tl = lines[i].strip()
                if not re.match(r'^\|[\s\-:|]+\|$', tl):
                    table_lines.append(tl)
                i += 1

            if table_lines:
                html.append('<div class="table-wrap"><table>')
                for ri, tl in enumerate(table_lines):
                    cells = [c.strip() for c in tl.strip('|').split('|')]
                    tag = 'th' if ri == 0 else 'td'
                    html.append('<tr>')
                    for cell in cells:
                        html.append('<{}>{}</{}>'.format(tag, inline_fmt(cell), tag))
                    html.append('</tr>')
                html.append('</table></div>')
            continue

        # Code block
        if stripped.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code_text = '\n'.join(code_lines)
            code_text = code_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html.append('<pre><code>{}</code></pre>'.format(code_text))
            continue

        # Bullet list
        if stripped.startswith('- ') or stripped.startswith('* '):
            list_items = []
            while i < len(lines):
                l = lines[i]
                s = l.strip()
                if not s:
                    i += 1
                    continue
                if s.startswith('- ') or s.startswith('* '):
                    indent = len(l) - len(l.lstrip())
                    level = indent // 2
                    text = s[2:]
                    list_items.append((level, text))
                    i += 1
                elif s.startswith('  ') and list_items:
                    indent = len(l) - len(l.lstrip())
                    if s.lstrip().startswith('- ') or s.lstrip().startswith('* '):
                        level = indent // 2
                        text = s.lstrip()[2:]
                        list_items.append((level, text))
                    else:
                        last_level, last_text = list_items[-1]
                        list_items[-1] = (last_level, last_text + ' ' + s)
                    i += 1
                else:
                    break

            def build_list(items, start_idx, base_level):
                result = '<ul>'
                idx = start_idx
                while idx < len(items):
                    level, text = items[idx]
                    if level < base_level:
                        break
                    if level == base_level:
                        result += '<li>{}'.format(inline_fmt(text))
                        if idx + 1 < len(items) and items[idx + 1][0] > base_level:
                            sub_html, idx = build_list(items, idx + 1, items[idx + 1][0])
                            result += sub_html
                        result += '</li>'
                        idx += 1
                    else:
                        idx += 1
                result += '</ul>'
                return result, idx

            list_html, _ = build_list(list_items, 0, 0)
            html.append(list_html)
            continue

        # Numbered list
        if re.match(r'^\d+\.', stripped):
            html.append('<ol>')
            while i < len(lines):
                s = lines[i].strip()
                if not s:
                    i += 1
                    continue
                m = re.match(r'^\d+\.\s*(.*)', s)
                if m:
                    html.append('<li>{}</li>'.format(inline_fmt(m.group(1))))
                    i += 1
                else:
                    break
            html.append('</ol>')
            continue

        # Paragraph
        html.append('<p>{}</p>'.format(inline_fmt(stripped)))
        i += 1

    if section_count > 0:
        html.append('</div></div>')

    return '\n'.join(html)


# Build all domain content
domains_html = []
toc_items = []

for idx, (fname, short_name, weight) in enumerate(FILES):
    domain_num = idx + 1
    fpath = os.path.join(STUDY_DIR, fname)
    if not os.path.exists(fpath):
        print("  Skipping (not found): {}".format(fname))
        continue

    with open(fpath, 'r', encoding='utf-8') as f:
        md_text = f.read()

    first_line = md_text.split('\n')[0]
    full_title = first_line.lstrip('# ').strip()

    content_html = md_to_html(md_text, domain_num)

    is_study_plan = (fname == "Study-Plan.md")

    if is_study_plan:
        domain_id = "study-plan"
        toc_items.append(("SP", short_name, weight, domain_id))
        domain_number_html = '<span class="domain-number plan-badge">PLAN</span>'
    else:
        domain_id = "domain-{}".format(domain_num)
        toc_items.append((domain_num, short_name, weight, domain_id))
        domain_number_html = '<span class="domain-number">Domain {}</span>'.format(domain_num)

    domains_html.append('''
    <div class="domain collapsed" id="{did}">
        <div class="domain-header" onclick="toggleDomain(this)">
            <div class="domain-title-row">
                {dnum}
                <h1 class="domain-title">{title}</h1>
            </div>
            <span class="domain-toggle">&#9660;</span>
        </div>
        <div class="domain-body">
            {content}
        </div>
    </div>
    '''.format(did=domain_id, dnum=domain_number_html, title=full_title, content=content_html))

    print("  Processed: {}".format(fname))

# Build TOC
toc_html = ""
for num, name, weight, did in toc_items:
    if num == "SP":
        extra_cls = " plan"
        num_label = "PLAN"
    else:
        extra_cls = ""
        num_label = num
    weight_html = '<span class="toc-weight">{}</span>'.format(weight) if weight else ''
    toc_html += '''<a href="#{did}" class="toc-item{cls}" onclick="showDomain(event, '{did}')">
        <span class="toc-num{cls}">{num}</span>
        <span class="toc-name">{name}</span>
        {wt}
    </a>\n'''.format(did=did, cls=extra_cls, num=num_label, name=name, wt=weight_html)


page_html = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Security Training - GlobeSec.ai</title>
<meta name="description" content="AWS Security Specialty (SCS-C03) study guide and training materials by GlobeSec.ai">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
    --bg: #0a1628;
    --bg2: #0f2744;
    --bg3: #162d50;
    --accent: #00d4ff;
    --accent2: #7b61ff;
    --aws: #ff9900;
    --text: #e0e8f0;
    --text-muted: #8899aa;
    --white: #ffffff;
    --gradient: linear-gradient(135deg, #00d4ff 0%, #7b61ff 100%);
    --border: rgba(0, 212, 255, 0.1);
}

body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}

/* Top bar */
.topbar {
    background: rgba(10, 22, 40, 0.95);
    backdrop-filter: blur(20px);
    color: #fff;
    padding: 0 1.5rem;
    display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 100;
    height: 60px;
    border-bottom: 1px solid var(--border);
}
.topbar-left { display: flex; align-items: center; gap: 1rem; }
.back-link {
    color: var(--accent); text-decoration: none; font-size: 0.85rem;
    display: flex; align-items: center; gap: 0.3rem; font-weight: 500;
}
.back-link:hover { text-decoration: underline; }
.topbar-title {
    font-size: 1rem; font-weight: 700; display: flex; align-items: center; gap: 0.6rem;
}
.aws-badge {
    background: var(--aws); color: #232f3e; padding: 0.15rem 0.5rem;
    border-radius: 4px; font-size: 0.7rem; font-weight: 800;
}
.globe-badge {
    background: var(--gradient); color: var(--bg); padding: 0.15rem 0.5rem;
    border-radius: 4px; font-size: 0.7rem; font-weight: 800;
}
.topbar-right { display: flex; gap: 0.75rem; align-items: center; }
.search-box { position: relative; }
.search-box input {
    padding: 0.4rem 0.8rem 0.4rem 2rem; border: 1px solid var(--border);
    border-radius: 6px; font-size: 0.85rem; width: 240px;
    background: var(--bg2); color: var(--text); outline: none;
}
.search-box input::placeholder { color: var(--text-muted); }
.search-box input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(0,212,255,0.15); }
.search-icon { position: absolute; left: 0.6rem; top: 50%; transform: translateY(-50%); color: var(--text-muted); font-size: 0.85rem; }
.topbar-btn {
    background: var(--bg3); color: var(--accent); border: 1px solid var(--border);
    padding: 0.35rem 0.7rem; border-radius: 6px;
    font-size: 0.78rem; font-weight: 600; cursor: pointer;
    transition: all 0.2s;
}
.topbar-btn:hover { background: var(--accent); color: var(--bg); }

/* Layout */
.layout { display: flex; min-height: calc(100vh - 60px); }

/* Sidebar */
.sidebar {
    width: 280px; background: var(--bg2); color: var(--text);
    padding: 1rem 0; position: sticky; top: 60px;
    height: calc(100vh - 60px); overflow-y: auto; flex-shrink: 0;
    border-right: 1px solid var(--border);
}
.sidebar-title {
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.5px;
    color: var(--text-muted); padding: 0.5rem 1.2rem; margin-bottom: 0.25rem;
}
.toc-item {
    display: flex; align-items: center; padding: 0.6rem 1.2rem; text-decoration: none;
    color: var(--text); gap: 0.6rem; transition: all 0.15s;
    border-left: 3px solid transparent;
}
.toc-item:hover { background: var(--bg3); color: var(--white); border-left-color: var(--accent); }
.toc-item.active { background: var(--bg3); color: var(--accent); border-left-color: var(--accent); }
.toc-num {
    background: var(--bg3); color: var(--aws); width: 24px; height: 24px;
    border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-size: 0.75rem; font-weight: 700; flex-shrink: 0;
}
.toc-item.active .toc-num { background: var(--aws); color: var(--bg); }
.toc-num.plan { background: var(--accent); color: var(--bg); font-size: 0.5rem; width: 32px; border-radius: 4px; }
.toc-name { font-size: 0.85rem; font-weight: 500; flex: 1; }
.toc-weight {
    font-size: 0.72rem; color: var(--text-muted); background: var(--bg);
    padding: 0.1rem 0.4rem; border-radius: 3px;
}

.progress-section { padding: 1rem 1.2rem; border-top: 1px solid var(--border); margin-top: 0.5rem; }
.progress-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); margin-bottom: 0.4rem; }
.progress-bar { background: var(--bg); border-radius: 4px; height: 6px; overflow: hidden; }
.progress-fill { background: var(--gradient); height: 100%; width: 0%; transition: width 0.3s; border-radius: 4px; }
.progress-text { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.3rem; }

/* Main content */
.main { flex: 1; padding: 1.5rem 2rem; max-width: 1000px; }

/* Domain card */
.domain {
    background: var(--bg2); border-radius: 10px; margin-bottom: 1.25rem;
    border: 1px solid var(--border); overflow: hidden;
}
.domain-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 1rem 1.5rem; cursor: pointer;
    background: linear-gradient(135deg, var(--bg2) 0%, var(--bg3) 100%);
    border-bottom: 1px solid var(--border);
}
.domain-header:hover { background: linear-gradient(135deg, #132d4f 0%, #1a3a63 100%); }
.domain-title-row { display: flex; align-items: center; gap: 0.75rem; }
.domain-number {
    background: var(--aws); color: #232f3e; padding: 0.2rem 0.6rem;
    border-radius: 4px; font-size: 0.75rem; font-weight: 800;
    text-transform: uppercase; white-space: nowrap;
}
.plan-badge { background: var(--gradient); color: var(--bg); }
.domain-title { font-size: 1.05rem; font-weight: 600; color: var(--white); }
.domain-toggle { font-size: 1.2rem; transition: transform 0.2s; color: var(--text-muted); }
.domain.collapsed .domain-toggle { transform: rotate(-90deg); }
.domain.collapsed .domain-body { display: none; }
.domain-body { padding: 0.5rem 1.5rem 1.5rem; }

/* Content styling */
.section { margin: 1rem 0; border-left: 3px solid var(--border); }
.section-title {
    font-size: 1rem; font-weight: 600; color: var(--white);
    padding: 0.5rem 0.75rem; cursor: pointer;
    display: flex; align-items: center; gap: 0.5rem; border-radius: 4px;
}
.section-title:hover { background: var(--bg3); }
.toggle-icon { font-size: 0.7rem; color: var(--text-muted); transition: transform 0.2s; width: 12px; }
.section-body { padding: 0.25rem 0 0.25rem 1.5rem; }

.cheatsheet-section {
    border-left-color: var(--aws); background: rgba(255,153,0,0.05);
    border-radius: 6px; padding: 0.25rem; margin: 1.25rem 0;
}
.cheatsheet-title { color: var(--aws) !important; }

h3 {
    font-size: 0.92rem; font-weight: 600; color: var(--accent); margin: 1rem 0 0.4rem;
    padding-bottom: 0.2rem; border-bottom: 1px solid rgba(0,212,255,0.1);
}
h4 { font-size: 0.85rem; font-weight: 600; color: var(--accent2); margin: 0.75rem 0 0.3rem; }

p { margin: 0.4rem 0; font-size: 0.88rem; }
a { color: var(--accent); }

ul, ol { margin: 0.3rem 0 0.5rem 1.25rem; }
li { font-size: 0.87rem; margin: 0.15rem 0; line-height: 1.5; }
li ul { margin: 0.1rem 0 0.15rem 1rem; }

strong { color: var(--white); }
code {
    background: rgba(0,212,255,0.08); color: #ff7eb6; padding: 0.1rem 0.35rem;
    border-radius: 3px; font-size: 0.82rem;
    font-family: 'Consolas', 'Monaco', monospace;
}

pre {
    background: #0d1b2a; color: #e2e8f0; padding: 1rem; border-radius: 6px;
    overflow-x: auto; margin: 0.5rem 0; font-size: 0.8rem; line-height: 1.5;
    border: 1px solid var(--border);
}
pre code { background: none; color: inherit; padding: 0; font-size: 0.8rem; }

/* Tables */
.table-wrap { overflow-x: auto; margin: 0.5rem 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.83rem; }
th {
    background: var(--bg3); color: var(--accent); padding: 0.45rem 0.65rem;
    text-align: left; font-weight: 600; font-size: 0.78rem;
    text-transform: uppercase; letter-spacing: 0.3px;
    border-bottom: 2px solid var(--accent);
}
td { padding: 0.4rem 0.65rem; border-bottom: 1px solid var(--border); }
tr:hover td { background: rgba(0,212,255,0.03); }

/* Search highlight */
mark { background: rgba(0,212,255,0.3); color: var(--white); padding: 0.1rem 0.15rem; border-radius: 2px; }

/* Responsive */
@media (max-width: 900px) {
    .sidebar { display: none; }
    .main { padding: 1rem; }
    .topbar-title span:last-child { display: none; }
}

/* Print */
@media print {
    .topbar, .sidebar, .topbar-btn { display: none; }
    .domain.collapsed .domain-body { display: block !important; }
    .section-body { display: block !important; }
    body { background: #fff; color: #000; }
}
</style>
</head>
<body>

<div class="topbar">
    <div class="topbar-left">
        <a href="index.html" class="back-link">&#8592; GlobeSec.ai</a>
        <div class="topbar-title">
            <span class="globe-badge">GlobeSec</span>
            <span class="aws-badge">AWS</span>
            <span>SCS-C03 Security Specialty Study Guide</span>
        </div>
    </div>
    <div class="topbar-right">
        <div class="search-box">
            <span class="search-icon">&#128269;</span>
            <input type="text" id="searchInput" placeholder="Search topics..." oninput="handleSearch(this.value)">
        </div>
        <button class="topbar-btn" onclick="expandAll()">Expand All</button>
        <button class="topbar-btn" onclick="collapseAll()">Collapse All</button>
    </div>
</div>

<div class="layout">
    <div class="sidebar">
        <div class="sidebar-title">Exam Domains</div>
        ''' + toc_html + '''
        <div class="progress-section">
            <div class="progress-label">Study Progress</div>
            <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
            <div class="progress-text" id="progressText">0 / 7 sections open</div>
        </div>
    </div>

    <div class="main" id="mainContent">
        ''' + "".join(domains_html) + '''
    </div>
</div>

<script>
function toggleDomain(header) {
    const domain = header.closest('.domain');
    domain.classList.toggle('collapsed');
    updateProgress();
}

function toggleSection(title) {
    const body = title.nextElementSibling;
    const icon = title.querySelector('.toggle-icon');
    if (body.style.display === 'none') {
        body.style.display = '';
        icon.innerHTML = '&#9660;';
    } else {
        body.style.display = 'none';
        icon.innerHTML = '&#9654;';
    }
}

function showDomain(e, domainId) {
    e.preventDefault();
    const domain = document.getElementById(domainId);
    if (domain.classList.contains('collapsed')) {
        domain.classList.remove('collapsed');
    }
    domain.scrollIntoView({ behavior: 'smooth', block: 'start' });
    document.querySelectorAll('.toc-item').forEach(t => t.classList.remove('active'));
    e.currentTarget.classList.add('active');
    updateProgress();
}

function expandAll() {
    document.querySelectorAll('.domain').forEach(d => d.classList.remove('collapsed'));
    document.querySelectorAll('.section-body').forEach(b => b.style.display = '');
    document.querySelectorAll('.toggle-icon').forEach(i => i.innerHTML = '&#9660;');
    updateProgress();
}
function collapseAll() {
    document.querySelectorAll('.domain').forEach(d => d.classList.add('collapsed'));
    updateProgress();
}

function handleSearch(query) {
    const main = document.getElementById('mainContent');
    main.querySelectorAll('mark').forEach(m => { m.replaceWith(m.textContent); });
    if (!query || query.length < 2) return;

    const regex = new RegExp('(' + query.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
    document.querySelectorAll('.domain').forEach(d => d.classList.remove('collapsed'));
    document.querySelectorAll('.section-body').forEach(b => b.style.display = '');

    function highlightNode(node) {
        if (node.nodeType === 3) {
            const text = node.textContent;
            if (regex.test(text)) {
                const span = document.createElement('span');
                span.innerHTML = text.replace(regex, '<mark>$1</mark>');
                node.replaceWith(span);
            }
        } else if (node.nodeType === 1 && !['SCRIPT', 'STYLE', 'INPUT', 'MARK'].includes(node.tagName)) {
            Array.from(node.childNodes).forEach(highlightNode);
        }
    }
    highlightNode(main);

    const firstMark = main.querySelector('mark');
    if (firstMark) firstMark.scrollIntoView({ behavior: 'smooth', block: 'center' });
    updateProgress();
}

function updateProgress() {
    const domains = document.querySelectorAll('.domain');
    const expanded = Array.from(domains).filter(d => !d.classList.contains('collapsed')).length;
    document.getElementById('progressFill').style.width = (expanded / domains.length * 100) + '%';
    document.getElementById('progressText').textContent = expanded + ' / ' + domains.length + ' sections open';
}

window.addEventListener('scroll', () => {
    const domains = document.querySelectorAll('.domain');
    let current = '';
    domains.forEach(d => {
        const rect = d.getBoundingClientRect();
        if (rect.top <= 100) current = d.id;
    });
    if (current) {
        document.querySelectorAll('.toc-item').forEach(t => {
            t.classList.toggle('active', t.getAttribute('href') === '#' + current);
        });
    }
});

updateProgress();
</script>
</body>
</html>'''

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(page_html)

print("Saved: {}".format(OUTPUT))
print("Size: {:.0f} KB".format(os.path.getsize(OUTPUT) / 1024))
