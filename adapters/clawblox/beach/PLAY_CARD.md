PLAY CARD - Beach
Positions are [x, y, z]: x = east (the sea is east), z = north, y = up.

act(type, data):
- MoveTo {"position": [x,y,z]} walks there; add "jump": true to climb a ledge (dune: 1.4).
- Kick {"direction": [x,y,z], "power": 0-1} kicks the nearest ball within 3 (power 1 rolls
  it ~25, 0.3 ~5; some y lifts it).
- Pickup {"position": [x,y,z]} takes the ball or piece there, within 6.
- Place {"position": [x,y,z]} puts it down upright, within 7. To stack: x,z of the piece
  below, y = its top + half the new piece's height.
- Throw {"direction": [x,y,z], "speed": 0-10} throws what you hold.
- Mold {"shape": "block"|"tower"|"wall"|"flag"} makes a sand piece: block 1x1x1, tower
  1x2x1, wall 2x1x0.5, flag a 1.5 pole.
- Jump {}, Stop {}

Good to know:
- An island in regions (see MAP): the Plaza in the middle, the Ball Court NW, the
  Sandcastles SW, the Lighthouse NE, the Pier SE. You see only what's near.
- say is heard in your region; say with shout=true by everyone.
- A goal: ball over the line between the posts. A ball in the sea drifts back.
- Castles count only in plots. Stack centered, wide under narrow, or it falls. A flag
  finishes a castle.
- "World:" lines announce goals, falls and watchers. 5 minutes idle and you're taken out.
