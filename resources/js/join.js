async function skipIfKnown() {
  const remembered = localStorage.getItem('mnj_guest') || '';
  if (!remembered) return;

  try {
    const data = await fetch('/jukebox/guests').then(r => r.json());
    if ((data.guests || []).some(guest => guest.id === remembered)) {
      window.location.replace('/player?guest=' + encodeURIComponent(remembered));
    }
  } catch (err) {
    // Stay on the choice page if the add-on has restarted.
  }
}

skipIfKnown();
