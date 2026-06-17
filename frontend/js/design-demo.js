// Design demo helper: loads SVGs inline, toggles portrait expressions, applies simple parallax, and exports SVG to PNG
(function(){
  const sceneUrl = '/frontend/assets/design/mockup-scene.svg';
  const portraitUrl = '/frontend/assets/design/mockup-portrait.svg';

  const sceneRoot = document.getElementById('scene-root');
  const portraitRoot = document.getElementById('portrait-root');
  const parallaxToggle = document.getElementById('parallax-toggle');

  function fetchText(url){ return fetch(url).then(r=>{ if(!r.ok) throw new Error('Failed to load '+url); return r.text(); }); }

  // Inline SVGs
  Promise.all([fetchText(sceneUrl), fetchText(portraitUrl)]).then(([sceneSvg, portraitSvg])=>{
    sceneRoot.innerHTML = sceneSvg;
    portraitRoot.innerHTML = portraitSvg;

    initParallax();
    initPortraitControls();
    wireExportButtons();
  }).catch(console.error);

  function initPortraitControls(){
    document.querySelectorAll('[data-expr]').forEach(btn=>{
      btn.addEventListener('click', ()=>{
        setExpression(btn.getAttribute('data-expr'));
      });
    });
    // default
    setExpression('idle');
  }

  function setExpression(name){
    const exprs = ['idle','happy','concerned'];
    exprs.forEach(e=>{
      const el = document.getElementById('expr-'+e);
      if(!el) return;
      el.style.opacity = (e===name)? '1' : '0';
      el.style.transition = 'opacity var(--cq-animation-fast) ease';
    });
  }

  function initParallax(){
    const sceneSvg = sceneRoot.querySelector('svg');
    if(!sceneSvg) return;
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(prefersReduced){ parallaxToggle.checked = false; parallaxToggle.disabled = true; }

    sceneRoot.addEventListener('mousemove', (ev)=>{
      if(!parallaxToggle.checked) return;
      const rect = sceneRoot.getBoundingClientRect();
      const cx = (ev.clientX - rect.left) / rect.width - 0.5; // -0.5..0.5
      const cy = (ev.clientY - rect.top) / rect.height - 0.5;
      // small transforms per layer
      applyLayerTransform('layer-far', cx*6, cy*3);
      applyLayerTransform('layer-mid', cx*10, cy*6);
      applyLayerTransform('layer-fg', cx*16, cy*10);
    });
    // reset on leave
    sceneRoot.addEventListener('mouseleave', ()=>{ ['layer-far','layer-mid','layer-fg'].forEach(id=>applyLayerTransform(id,0,0)); });
  }

  function applyLayerTransform(id, tx, ty){
    const el = document.getElementById(id);
    if(!el) return;
    el.style.transform = `translate(${tx}px, ${ty}px)`;
    el.style.transition = 'transform var(--cq-animation-fast) ease';
    el.style.willChange = 'transform';
  }

  // Export utilities
  function wireExportButtons(){
    document.getElementById('export-portrait').addEventListener('click', ()=>{
      const svg = portraitRoot.querySelector('svg');
      if(svg) exportSVGToPNG(svg, 'portrait.png', 1024);
    });
    document.getElementById('export-scene').addEventListener('click', ()=>{
      const svg = sceneRoot.querySelector('svg');
      if(svg) exportSVGToPNG(svg, 'scene.png', 1600);
    });
  }

  function exportSVGToPNG(svgElement, fileName, maxDim){
    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(svgElement);
    const svgBlob = new Blob([svgString], {type: 'image/svg+xml;charset=utf-8'});
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    img.onload = function(){
      const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      const ctx = canvas.getContext('2d');
      // white background
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0,0,canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob(function(blob){
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
      }, 'image/png');
    };
    img.onerror = function(e){ console.error('Image load error', e); URL.revokeObjectURL(url); };
    img.src = url;
  }

})();
