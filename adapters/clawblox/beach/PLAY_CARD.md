PLAY CARD - Beach
Positions are [x, y, z]: x = east (the sea is east), z = north, y = up.

act(type, data):
- MoveTo {"position": [x,y,z]} walks there.
- Kick {"direction": [x,y,z], "power": 0-1} kicks the nearest ball within 3 of you (stand
  next to it). Power 1 rolls a ball about 25, power 0.3 about 5. Some y lifts it.
- Pickup {"position": [x,y,z]} takes the ball or piece there (from look), within 6.
- Place {"position": [x,y,z]} puts it down upright, within 7. To stack: x,z of the piece
  below, y = its top + half the new piece's height.
- Throw {"direction": [x,y,z], "speed": 0-10} throws what you hold.
- Mold {"shape": "block"|"tower"|"wall"|"flag"} makes a sand piece in your hands:
  block 1x1x1, tower 1x2x1, wall 2x1x0.5, flag a 1.5 pole.
- Jump {}, Stop {}

Good to know:
- Soccer ball: medium. Volleyball: light, bouncy. Beach ball: floats, drifts.
- Goals at the north and south ends: a ball over the line between the posts scores, then
  goes back to the centre.
- A ball in the sea drifts back to the sand.
- Castles only count inside plots. Badly balanced pieces fall: stack them centred, wide
  under narrow. A flag finishes a castle.
- "World:" chat lines announce goals and falls.
