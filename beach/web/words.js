// The words the Beach's pages show, in one place: a later translation means swapping this file.
// One language per Beach (American English here). Plain JavaScript, no build step.
//   T.t('bell_rang', { name: 'Pebble' })  ->  "Pebble rang the Gather Bell. Come to the chat?"
'use strict'

const T = (() => {
  const WORDS = {
    // the top bar and its menu
    map: 'Map',
    keeper: 'Keeper',
    zones: 'Zones',
    my_look: 'My look',
    sign_out: 'Sign out',
    closed: 'closed',
    ok: 'OK',
    someone: 'Someone',
    // the Gather Bell
    bell_rang: '{name} rang the Gather Bell. Come to the chat?',
    ring_bell: 'Ring the Gather Bell',
    bell_hint: 'Invites people who are away. An invitation, not a summons.',
    come: 'Come',
    not_now: 'Not now',
    // being somewhere
    you_here: "You're here",
    you_playing: "You're playing",
    you_watching: "You're watching",
    leave: 'Leave',
    leave_zone: 'Leave {zone}',
    open: 'Open',
    go_in: 'Go in',
    play: 'Play',
    watch: 'Watch',
    stop_watching: 'Stop watching',
    play_again: 'Play again',
    // the map
    quiet: 'The beach is quiet.',
    nobody_here: 'nobody here',
    n_here: '{n} here',
    n_playing: '{n} playing',
    n_watching: '{n} watching',
    watching_tag: 'watching',
    // a game world's page
    world_choose: 'Play puts your character on the sand. Watch gives you a seat at the edge of the world: your name shows there, and everyone in the world can see you\'re watching.',
    world_not_connected: "{zone} isn't connected to the Beach right now (its bridge isn't running).",
    world_playing: 'Your character is in {zone}. The world takes out anyone idle for {limit}.',
    world_playing_plain: 'Your character is in {zone}.',
    world_watching: "You're watching {zone}. Your name shows at the watch spot; you have no character there.",
    world_left: 'You left {zone}.',
    world_stopped_watching: 'You stopped watching {zone}.',
    world_no_viewer: '{zone} has no viewer address yet; the keeper can set one.',
    // tables
    leave_table: 'Leave table',
    back_to_tables: 'Back to the tables',
    leave_boardwalk: 'Leave {zone}'
  }

  function t (key, vars) {
    let s = WORDS[key]
    if (s === undefined) return key
    for (const [k, v] of Object.entries(vars || {})) s = s.split('{' + k + '}').join(String(v))
    return s
  }
  const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : s
  return { t, cap, WORDS }
})()
