(function(){
  var HASH = '301b8e3e40a10ec3e745b06aebe05a3d6e6a023913469ed4499399c621daf6cb';
  var KEY = 'rw_gate_token';
  if (localStorage.getItem(KEY) === HASH) return;

  document.documentElement.style.overflow = 'hidden';
  var overlay = document.createElement('div');
  overlay.id = 'gateOverlay';
  overlay.innerHTML =
    '<div style="position:fixed;inset:0;background:#0a0a0f;z-index:99999;display:flex;align-items:center;justify-content:center">' +
    '<div style="text-align:center;max-width:360px;padding:2rem">' +
    '<div style="font-size:2.5rem;margin-bottom:1rem">🔒</div>' +
    '<h2 style="color:#e0e0e0;font-size:1.3rem;margin-bottom:0.5rem">RiverWatch Beta</h2>' +
    '<p style="color:#888;font-size:0.85rem;margin-bottom:1.5rem">시범운영 중입니다. 접속 코드를 입력해주세요.</p>' +
    '<input id="gateInput" type="password" placeholder="접속 코드" ' +
    'style="width:100%;padding:0.8rem 1rem;background:#12121a;border:1px solid #333;border-radius:10px;color:#e0e0e0;font-size:1rem;text-align:center;outline:none;margin-bottom:0.8rem" />' +
    '<button id="gateBtn" style="width:100%;padding:0.8rem;background:#7873f5;color:#fff;border:none;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer">입장</button>' +
    '<p id="gateError" style="color:#e74c3c;font-size:0.8rem;margin-top:0.8rem;display:none">접속 코드가 올바르지 않습니다.</p>' +
    '</div></div>';

  function ready(fn) {
    if (document.body) fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function() {
    document.body.appendChild(overlay);
    var inp = document.getElementById('gateInput');
    var btn = document.getElementById('gateBtn');
    var err = document.getElementById('gateError');

    function check() {
      var pw = inp.value;
      crypto.subtle.digest('SHA-256', new TextEncoder().encode(pw)).then(function(buf) {
        var hex = Array.from(new Uint8Array(buf)).map(function(b) {
          return b.toString(16).padStart(2, '0');
        }).join('');
        if (hex === HASH) {
          localStorage.setItem(KEY, HASH);
          overlay.remove();
          document.documentElement.style.overflow = '';
        } else {
          err.style.display = 'block';
          inp.value = '';
          inp.focus();
        }
      });
    }

    btn.addEventListener('click', check);
    inp.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') check();
    });
    inp.focus();
  });
})();
