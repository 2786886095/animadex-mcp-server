with open('app.py', 'r', encoding='utf-8') as f:
    t = f.read()

# Build the image src logic:
# local:  /api/image?url=CDN
# remote: CDN with onerror -> /api/image?url=CDN
card_src = '''" onerror="this.onerror=null;this.src=\\'/api/image?url=\\'+encodeURIComponent(this.src)" alt="" loading="lazy">':'<div style="color:#333;display:flex;align-items:center;justify-content:center;height:100%;font-size:12px">无图</div>\')+'''
detail_src = '''" onerror="this.onerror=null;this.src=\\'/api/image?url=\\'+encodeURIComponent(this.src)" alt="" onclick="window.open(this.src)">\':\'\';'''

# Replace using simple string - find current src patterns and replace
# Current card pattern is embedded in a long line
# Let me find the exact current patterns

# Card: src="'+(isLocal?'/api/image?url='+img+'':img)+'"
old_card = """src="'+(isLocal?'/api/image?url='+img+'':img)+'" alt="" loading="lazy">':'"""
new_card = """src="'+(isLocal?'/api/image?url='+img+''':img)+'" onerror="'+(isLocal?'':\\'this.onerror=null;this.src=\\\\'/api/image?url=\\\\'+encodeURIComponent(this.src)\\\')+'" alt="" loading="lazy">':'"""
t = t.replace(old_card, new_card)

# Detail
old_detail = """src="'+(isLocal?'/api/image?url='+img+'':img)+'" alt="" onclick="window.open(this.src)">'''
new_detail = """src="'+(isLocal?'/api/image?url='+img+''':img)+'" onerror="'+(isLocal?'':\\'this.onerror=null;this.src=\\\\'/api/image?url=\\\\'+encodeURIComponent(this.src)\\\')+'" alt="" onclick="window.open(this.src)">\':\'\';"""
t = t.replace(old_detail, new_detail)

# Hide AI settings on HF Space
old_set = """function showSettings(){"""
new_set = """function showSettings(){
  var isLocal=location.hostname==='127.0.0.1'||location.hostname==='localhost';
  if(!isLocal){"""
t = t.replace(old_set, new_set)

# Add remote-only API info to settings
old_api_info = """  var o=document.createElement('div');
  o.className='detail-overlay open';"""
new_api_info = """    var o=document.createElement('div');
    o.className='detail-overlay open';
    o.innerHTML='<div class="detail-panel" style="max-width:500px"><div class="detail-body">'
    +'<h3 style="margin-bottom:16px">🔌 API 信息</h3>'
    +'<div style="background:#0d0d1a;border-radius:8px;padding:12px;margin-bottom:12px;font-size:13px">'
    +'<div style="color:#888;margin-bottom:4px">MCP 地址</div>'
    +'<code style="color:#f0c060;word-break:break-all;font-size:12px">'+window.location.origin+'/sse</code>'
    +'</div>'
    +'<div style="background:#0d0d1a;border-radius:8px;padding:12px;font-size:13px">'
    +'<div style="color:#888;margin-bottom:4px">翻译方式</div>'
    +'<div style="color:#aaa;font-size:12px">Google 翻译</div>'
    +'</div>'
    +'</div><button onclick="closeSettings()" style="display:block;width:100%;padding:12px;border:none;border-top:1px solid #2a2a3e;background:transparent;color:#888;font-size:14px;cursor:pointer">关闭</button></div>';
    document.body.appendChild(o);
    return;
  }
  var o=document.createElement('div');
  o.className='detail-overlay open';"""

t = t.replace(old_api_info, new_api_info)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(t)

import py_compile
py_compile.compile('app.py', doraise=True)
print('OK')
