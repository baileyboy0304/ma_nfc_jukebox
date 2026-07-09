let guests = [];
let activeGuestId = '';
let activeGuest = null;
let activePlaylist = null;
let players = [];
let activePlayerId = '';
let isPaused = true;
let currentProgressMs = 0;
let currentDurationMs = 0;
let lastProgressAt = 0;
// True until a guest is explicitly picked (via ?guest= on load, or manually
// from the dropdown/list) -- while true, this screen follows whichever
// guest most recently connected (the shared sidebar/ingress "now showing"
// view). A guest's own phone always arrives with ?guest= set, so it never
// auto-follows someone else.
let autoFollow = true;
let lastGuestsSignature = '';
let lastVolumeInteraction = 0;

// Lucide icon geometry (matches Music Assistant / NewLyricsJukebox).
const PLAY_ICON = '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" />';
const PAUSE_ICON = '<rect x="14" y="3" width="5" height="18" rx="1" /><rect x="5" y="3" width="5" height="18" rx="1" />';

function $(id) {
  return document.getElementById(id);
}

function esc(value) {
  return String(value || '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]));
}

function toast(message, isError = false) {
  const el = $('toast');
  el.textContent = message || '';
  el.style.color = isError ? 'var(--danger)' : 'var(--text)';
  el.classList.toggle('show', Boolean(message));
  clearTimeout(window.toastTimer);
  if (message) {
    window.toastTimer = setTimeout(() => el.classList.remove('show'), 4200);
  }
}

function initials(name) {
  return (name || '?').trim().slice(0, 1).toUpperCase() || '?';
}

function formatDuration(ms) {
  const total = Math.max(0, Math.floor((ms || 0) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function playbackReady() {
  return Boolean(activePlayerId);
}

function updateControls() {
  const ready = playbackReady();
  $('playPause').disabled = !ready;
  $('btnPrev').disabled = !ready;
  $('btnNext').disabled = !ready;
  $('volume').disabled = !activePlayerId;
  $('playPauseIcon').innerHTML = isPaused ? PLAY_ICON : PAUSE_ICON;
}

async function loadGuests() {
  const data = await fetch('jukebox/guests').then(r => r.json());
  guests = data.guests || [];
  const requestedGuest = new URLSearchParams(window.location.search).get('guest') || '';
  if (requestedGuest) {
    autoFollow = false;
  }

  const previousActiveId = activeGuestId;
  if (!activeGuestId || autoFollow) {
    activeGuestId = requestedGuest || data.selected_guest_id || (guests[0] && guests[0].id) || '';
  }
  if (!guests.some(g => g.id === activeGuestId)) {
    activeGuestId = (guests[0] && guests[0].id) || '';
  }
  activeGuest = guests.find(g => g.id === activeGuestId) || null;
  if (activeGuestId) {
    localStorage.setItem('mnj_guest', activeGuestId);
  }

  const signature = JSON.stringify(guests.map(g => [g.id, g.display_name, g.playlists.length]));
  if (signature !== lastGuestsSignature) {
    lastGuestsSignature = signature;
    renderGuests();
  }
  if (activeGuestId !== previousActiveId) {
    showPlaylists();
    renderPlaylists();
  }
}

function renderGuests() {
  const select = $('guestSelect');
  select.innerHTML = '';

  if (!guests.length) {
    const option = document.createElement('option');
    option.textContent = 'No guests yet';
    option.value = '';
    select.appendChild(option);
  }

  for (const guest of guests) {
    const option = document.createElement('option');
    option.value = guest.id;
    option.textContent = guest.display_name || guest.user_id || 'Guest';
    option.selected = guest.id === activeGuestId;
    select.appendChild(option);
  }

  select.onchange = () => {
    autoFollow = false;
    activeGuestId = select.value;
    activeGuest = guests.find(g => g.id === activeGuestId) || null;
    if (activeGuestId) {
      localStorage.setItem('mnj_guest', activeGuestId);
    }
    showPlaylists();
    renderGuests();
    renderPlaylists();
  };

  const list = $('guestList');
  list.innerHTML = '';
  for (const guest of guests) {
    const row = document.createElement('div');
    row.className = 'guest-row' + (guest.id === activeGuestId ? ' active' : '');
    row.dataset.id = guest.id;

    const bg = document.createElement('div');
    bg.className = 'guest-delete-bg';
    bg.textContent = 'Delete';

    const button = document.createElement('button');
    button.className = 'guest-row-content';
    button.type = 'button';
    button.innerHTML = `
      <span class="avatar">${esc(initials(guest.display_name || guest.user_id))}</span>
      <span class="guest-copy">
        <span class="guest-name">${esc(guest.display_name || guest.user_id || 'Guest')}</span>
        <span class="guest-sub">${guest.playlists.length} playlists</span>
      </span>
    `;
    button.onclick = () => {
      autoFollow = false;
      activeGuestId = guest.id;
      activeGuest = guests.find(g => g.id === activeGuestId) || null;
      localStorage.setItem('mnj_guest', activeGuestId);
      showPlaylists();
      renderGuests();
      renderPlaylists();
    };

    addSwipeDelete(row, button, guest.id);
    row.appendChild(bg);
    row.appendChild(button);
    list.appendChild(row);
  }
}

function addSwipeDelete(row, content, guestId) {
  let startX = 0;
  let currentX = 0;
  let dragging = false;

  row.addEventListener('pointerdown', (event) => {
    startX = event.clientX;
    currentX = 0;
    dragging = true;
    row.setPointerCapture(event.pointerId);
  });

  row.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    currentX = Math.min(0, event.clientX - startX);
    content.style.transform = `translateX(${Math.max(currentX, -92)}px)`;
  });

  row.addEventListener('pointerup', async () => {
    if (!dragging) return;
    dragging = false;
    if (currentX < -76) {
      await deleteGuest(guestId);
    } else {
      content.style.transform = '';
    }
  });
}

async function deleteGuest(guestId) {
  const res = await fetch('jukebox/delete-guest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ guest_id: guestId })
  });
  const data = await res.json();
  if (!res.ok) {
    toast(data.error || 'Could not delete guest.', true);
    return;
  }
  activeGuestId = data.selected_guest_id || '';
  activePlaylist = null;
  await loadGuests();
  showPlaylists();
}

function renderPlaylists() {
  const grid = $('playlistGrid');
  grid.innerHTML = '';

  if (!activeGuest) {
    $('libraryTitle').textContent = 'Shared playlists';
    $('librarySubtitle').textContent = 'Tap the NFC tag or open /join to add a guest.';
    grid.innerHTML = '<div class="empty panel">No guests yet.</div>';
    return;
  }

  $('libraryTitle').textContent = activeGuest.display_name || activeGuest.user_id || 'Guest';
  $('librarySubtitle').textContent = `${activeGuest.playlists.length} playlists shared with the room.`;

  if (!activeGuest.playlists.length) {
    grid.innerHTML = '<div class="empty panel">No playlists were shared.</div>';
    return;
  }

  for (const playlist of activeGuest.playlists) {
    const card = document.createElement('div');
    card.className = 'playlist-card';
    card.role = 'button';
    card.tabIndex = 0;
    card.innerHTML = `
      <img class="art" src="${esc(playlist.image || '')}" alt="">
      <button class="playlist-play" type="button" title="Play playlist" aria-label="Play ${esc(playlist.name)}">
        <svg class="transport-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8 5.2v13.6L18.8 12z"></path>
        </svg>
      </button>
      <div class="playlist-name">${esc(playlist.name)}</div>
      <p class="playlist-meta">${playlist.tracks_total} tracks &middot; ${esc(playlist.public_text)}</p>
    `;
    card.querySelector('.playlist-play').onclick = (event) => {
      event.stopPropagation();
      playPlaylist(playlist);
    };
    card.onclick = () => openPlaylist(playlist.id);
    card.onkeydown = (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openPlaylist(playlist.id);
      }
    };
    grid.appendChild(card);
  }
}

function showPlaylists() {
  $('playlistView').classList.remove('hidden');
  $('trackView').classList.remove('open');
  activePlaylist = null;
}

async function openPlaylist(playlistId) {
  if (!activeGuest) return;
  const data = await fetch(`jukebox/tracks?guest_id=${encodeURIComponent(activeGuest.id)}&playlist_id=${encodeURIComponent(playlistId)}`).then(r => r.json());
  if (data.error) {
    toast(data.error, true);
    return;
  }
  activePlaylist = data.playlist;
  $('playlistView').classList.add('hidden');
  $('trackView').classList.add('open');
  $('trackPlaylistImage').src = activePlaylist.image || '';
  $('trackPlaylistName').textContent = activePlaylist.name || 'Playlist';
  $('trackPlaylistMeta').textContent = `${activePlaylist.tracks.length} tracks · ${activePlaylist.public_text}`;
  renderTracks();
}

function renderTracks() {
  const list = $('trackList');
  list.innerHTML = '';

  if (!activePlaylist || !activePlaylist.tracks.length) {
    list.innerHTML = '<div class="empty panel">No playable tracks were found in this playlist.</div>';
    return;
  }

  activePlaylist.tracks.forEach((track, index) => {
    const row = document.createElement('button');
    row.className = 'track-row';
    row.type = 'button';
    row.innerHTML = `
      <span class="track-index">${index + 1}</span>
      <span class="track-main">
        <span class="track-name">${esc(track.name)}</span>
        <span class="track-artist">${esc(track.artists || 'Unknown artist')}</span>
      </span>
      <span class="track-duration">${formatDuration(track.duration_ms)}</span>
    `;
    row.onclick = () => playTrack(track);
    list.appendChild(row);
  });
}

function updateProgress(position, duration) {
  const pct = Math.max(0, Math.min(100, (position / duration) * 100));
  $('progressFill').style.width = `${pct}%`;
  $('elapsedTime').textContent = formatDuration(position);
  $('durationTime').textContent = formatDuration(duration);
}

function renderPlaybackState(state) {
  if (!state || !state.has_playback) {
    isPaused = true;
    currentProgressMs = 0;
    currentDurationMs = 0;
    lastProgressAt = 0;
    $('nowTitle').textContent = 'Nothing playing';
    $('nowSubtitle').textContent = activePlayerId ? 'Ready to play.' : 'Choose a speaker to start.';
    $('nowArt').src = '';
    updateProgress(0, 1);
    updateControls();
    return;
  }

  isPaused = !state.is_playing;
  currentProgressMs = state.progress_ms || 0;
  currentDurationMs = state.duration_ms || 0;
  lastProgressAt = Date.now();

  $('nowTitle').textContent = state.name || 'Playing';
  $('nowSubtitle').textContent = state.artists || (state.player_name ? `Playing on ${state.player_name}` : 'Music Share');
  $('nowArt').src = state.image || '';
  updateProgress(currentProgressMs, currentDurationMs || 1);
  updateControls();
}

async function refreshPlaybackState() {
  if (!activePlayerId) {
    renderPlaybackState(null);
    return;
  }
  try {
    const state = await fetch(`jukebox/playback-state?player_id=${encodeURIComponent(activePlayerId)}`).then(r => r.json());
    if (!state.error) {
      renderPlaybackState(state);
    }
  } catch (err) {
    // Keep the last known playback display if polling misses once.
  }
}

function tickProgress() {
  if (!currentDurationMs || isPaused || !lastProgressAt) return;
  const elapsed = Date.now() - lastProgressAt;
  updateProgress(Math.min(currentDurationMs, currentProgressMs + elapsed), currentDurationMs);
}

function availablePlayers() {
  // Unavailable players can't accept commands (MA rejects them with
  // "Player X is not available") -- don't offer them at all.
  return players
    .filter(p => p.available !== false)
    .sort((a, b) => (a.name || '').localeCompare(b.name || ''));
}

function activePlayer() {
  return players.find(p => p.player_id === activePlayerId) || null;
}

function updateSpeakerName(name) {
  $('speakerName').textContent = name || 'Select speaker';
}

// Reflect the selected player's real volume in the slider, unless the user is
// actively adjusting it (dragging, or within a moment of their last change).
function syncVolume(player) {
  const slider = $('volume');
  if (document.activeElement === slider) return;
  if (Date.now() - lastVolumeInteraction < 2500) return;
  if (player && typeof player.volume_level === 'number') {
    slider.value = player.volume_level;
  }
}

async function refreshDevices() {
  const data = await fetch('jukebox/devices').then(r => r.json()).catch(() => ({ players: [] }));
  players = data.players || [];
  const available = availablePlayers();

  if (!available.length) {
    activePlayerId = '';
    updateSpeakerName(data.connected ? 'No speakers available' : 'Music Assistant offline');
    updateControls();
    return;
  }

  // Keep the current choice if it's still valid; otherwise the speaker used
  // last time (remembered per browser), then the configured default player,
  // then the first available one.
  const remembered = localStorage.getItem('mnj_player') || '';
  activePlayerId = [activePlayerId, remembered, data.preferred_player_id, available[0].player_id]
    .find(id => id && available.some(p => p.player_id === id));

  const player = activePlayer();
  updateSpeakerName(player ? player.name : 'Select speaker');
  syncVolume(player);
  // Reflect the current selection live if the picker modal is open.
  if ($('playerModal').classList.contains('open')) renderPlayerList();
  updateControls();
}

function selectDevice(playerId) {
  activePlayerId = playerId;
  if (playerId) {
    localStorage.setItem('mnj_player', playerId);
  }
  const player = activePlayer();
  updateSpeakerName(player ? player.name : 'Select speaker');
  syncVolume(player);
  updateControls();
  refreshPlaybackState();
}

// ---------- speaker picker modal ----------

function openPlayerModal() {
  renderPlayerList();
  $('playerModal').classList.add('open');
}

function closePlayerModal() {
  $('playerModal').classList.remove('open');
}

function closePlayerModalBackdrop(event) {
  if (event.target.id === 'playerModal') closePlayerModal();
}

function renderPlayerList() {
  const list = $('playerList');
  list.innerHTML = '';
  const available = availablePlayers();

  if (!available.length) {
    const empty = document.createElement('div');
    empty.className = 'player-row-meta';
    empty.textContent = 'No speakers are available right now.';
    list.appendChild(empty);
    return;
  }

  for (const p of available) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'player-row' + (p.player_id === activePlayerId ? ' active' : '');
    row.innerHTML = `
      <span class="player-row-info">
        <span class="player-row-name">${esc(p.name)}</span>
        ${p.is_playing ? '<span class="player-row-meta">Playing</span>' : ''}
      </span>
      <span class="player-row-check">&#10003;</span>
    `;
    row.onclick = () => {
      selectDevice(p.player_id);
      closePlayerModal();
    };
    list.appendChild(row);
  }
}

async function playCurrentPlaylist() {
  if (!activePlaylist) return;
  await playPlaylist(activePlaylist);
}

async function playPlaylist(playlist) {
  await playRequest({
    context_uri: playlist.uri,
    display_name: playlist.name,
    image: playlist.image
  });
}

async function playTrack(track) {
  if (!activePlaylist) return;
  await playRequest({
    context_uri: activePlaylist.uri,
    track_uri: track.uri,
    display_name: track.name,
    artists: track.artists,
    image: track.image || activePlaylist.image
  });
}

let playPending = false;

async function playRequest(payload) {
  if (!activePlayerId) {
    toast('Choose a speaker first.', true);
    return;
  }
  // A play request can take a couple of seconds while Music Assistant
  // resolves the playlist -- ignore double-taps instead of firing twice.
  if (playPending) return;
  playPending = true;
  toast('Starting playback…');

  try {
    payload.player_id = activePlayerId;
    const res = await fetch('jukebox/play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) {
      toast(data.error || 'Playback could not start.', true);
      return;
    }

    $('nowTitle').textContent = payload.display_name || 'Playing';
    $('nowSubtitle').textContent = payload.artists || 'Music Share';
    $('nowArt').src = payload.image || '';
    toast('Playing.');
    setTimeout(refreshPlaybackState, 700);
  } catch (err) {
    toast('Playback could not start.', true);
  } finally {
    playPending = false;
  }
}

async function transportRequest(action) {
  if (!activePlayerId) {
    toast('Choose a speaker first.', true);
    return false;
  }

  const res = await fetch('jukebox/transport', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, player_id: activePlayerId })
  });
  const data = await res.json();
  if (!res.ok) {
    toast(data.error || 'Playback control failed.', true);
    setTimeout(refreshPlaybackState, 700);
    return false;
  }
  setTimeout(refreshPlaybackState, 700);
  return true;
}

async function togglePlay() {
  const ok = await transportRequest(isPaused ? 'resume' : 'pause');
  if (ok) {
    isPaused = !isPaused;
    updateControls();
  }
}

async function nextTrack() {
  await transportRequest('next');
}

async function previousTrack() {
  await transportRequest('previous');
}

async function setVolume(value) {
  if (!activePlayerId) return;
  // Mark the interaction so refreshDevices doesn't snap the slider back to the
  // (slightly stale) reported level while the user is still adjusting it.
  lastVolumeInteraction = Date.now();
  const player = activePlayer();
  if (player) player.volume_level = Number(value);
  const res = await fetch('jukebox/volume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_id: activePlayerId, volume_percent: Number(value) })
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    toast(data.error || 'Volume could not be changed.', true);
  }
}

async function boot() {
  await loadGuests();
  await refreshDevices();
  await refreshPlaybackState();
}

boot();
setInterval(refreshPlaybackState, 1600);
setInterval(tickProgress, 500);
setInterval(refreshDevices, 10000);
setInterval(loadGuests, 4000);
