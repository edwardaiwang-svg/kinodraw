// The project's music, paper and hand, beside its format (studio/server.py: save_music and set_options).
// app.js calls projectOptions(name, p) each time it opens a project; this file only uses app.js's helpers.
function projectOptions(name, p) {
  const music = $('#p-music'), file = $('#p-music-file'), paper = $('#p-paper'), color = $('#p-paper-color'), hand = $('#p-hand');
  if (!music) return;
  const b = p.storyboard, own = b.music && typeof b.music === 'object' && b.music.file;
  const chosen = own ? 'own' : b.music === false ? 'none' : 'auto';
  music.value = chosen;
  if (own) music.querySelector('option[value="own"]').textContent = `Music: ${own.split('/').pop()}`;
  paper.value = b.paper || 'plain';
  color.value = b.paper_color || '#ecebe6';
  color.disabled = paper.value === 'kraft';
  hand.value = b.hand || 'right';
  paper.hidden = color.hidden = (b.look || 'whiteboard') !== 'whiteboard';    // other looks keep their own board
  hand.hidden = b.look === 'collage';
  const send = async (path, body, done) => {
    try {
      if (dirty && !(await saveBoard())) return;
      await api(`/api/projects/${encodeURIComponent(name)}/${path}`, { method: 'POST', body });
      await openProject(name); toast(`${done} Make video to apply it.`, 5000);
    } catch (e) { toast(e.message, 8000); openProject(name); }
  };
  music.onchange = () => {
    if (music.value === 'own') { music.value = chosen; file.click(); return; }
    send('music', JSON.stringify({ music: music.value }), music.value === 'none' ? 'No music.' : 'Automatic music.');
  };
  file.onchange = () => {
    const f = file.files[0]; if (!f) return;
    toast(`Checking “${f.name}” and finding its beat…`, 30000);
    send(`music?filename=${encodeURIComponent(f.name)}`, f, `Your music: ${f.name}.`);
  };
  paper.onchange = () => send('options', JSON.stringify({ paper: paper.value }), 'Paper saved.');
  color.onchange = () => send('options', JSON.stringify({ paper_color: color.value }), 'Paper colour saved.');
  hand.onchange = () => send('options', JSON.stringify({ hand: hand.value }), 'Hand saved.');
}
