PLAY CARD - Mesa Island
You are a character on an island. Positions are [x, y, z]: x = east, z = north, y = up.

act(type, data):
- MoveTo {"position": [x,y,z]} walks there; says arrived or why it stopped. It can't climb:
  to get onto anything higher add "jump": true (run-up done for you; ledges up to ~6 high).
- Jump {} jumps on the spot. Stop {} stops walking.
- Pickup {"position": [x,y,z]} takes the object at that position (copy it from look).
  You must be within 6 of it, and the point within 1.5 of the object. You hold one thing.
- Place {"position": [x,y,z]} puts it down upright, within 7 of you, at y = 0.6 on the
  ground (or a platform's top + 0.6). Fails if something is already there.
- Throw {"direction": [x,y,z], "speed": 0-10} throws what you hold. Speed is capped at 10.
  East is [1,0,0], north [0,0,1]; add y to throw upward.

Good to know:
- Blocks, the rock and the ring can be picked up.
- The rock is heavy. Throw it so it hits something hard and new blocks burst out (up to 8).
  That is the only way to get more blocks.
- There is no score or goal: build, explore, talk.
- Failed actions say why and what to try. Read the result before retrying.
