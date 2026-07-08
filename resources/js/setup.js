async function refreshSetup() {
  const [status, devices, guests] = await Promise.all([
    fetch('jukebox/status').then(r => r.json()),
    fetch('jukebox/devices').then(r => r.json()),
    fetch('jukebox/guests').then(r => r.json())
  ]);
  document.getElementById('maStatus').textContent = status.connected ? 'Connected' : 'Not connected';
  document.getElementById('playerCount').textContent = `${(devices.players || []).length} available`;
  document.getElementById('guestCount').textContent = `${guests.guests.length} remembered`;
}

refreshSetup();
setInterval(refreshSetup, 4000);
