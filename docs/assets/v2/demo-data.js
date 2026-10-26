window.DEMO = {
 "animation": {
  "checks": [
   {
    "id": "frames",
    "status": "pass",
    "detail": "6 of 6 frames found",
    "frames": []
   },
   {
    "id": "source-edge",
    "status": "pass",
    "detail": "no frame touches the source image edge",
    "frames": []
   },
   {
    "id": "specks",
    "status": "pass",
    "detail": "no stray specks",
    "frames": []
   },
   {
    "id": "scale",
    "status": "pass",
    "detail": "every frame within 1% of the row's size",
    "frames": []
   },
   {
    "id": "color",
    "status": "pass",
    "detail": "color and lighting match across frames (max difference 1.7)",
    "frames": []
   },
   {
    "id": "identity",
    "status": "pass",
    "detail": "palette matches the anchor (max distance 0.20)",
    "frames": []
   },
   {
    "id": "motion",
    "status": "pass",
    "detail": "average change between frames 0.044",
    "frames": []
   },
   {
    "id": "cell-edge",
    "status": "pass",
    "detail": "every frame fits inside its cell",
    "frames": []
   },
   {
    "id": "match",
    "status": "pass",
    "detail": "color and light match idle (difference 0.8)",
    "frames": []
   }
  ]
 },
 "gestures": [
  "wave",
  "point",
  "thumbs-up",
  "arms-crossed",
  "think",
  "shrug",
  "cheer",
  "bow"
 ],
 "icons": [
  "heart",
  "coin",
  "gem",
  "key",
  "potion",
  "shield",
  "sword",
  "star"
 ],
 "buttons": [
  "normal",
  "hover",
  "pressed",
  "disabled"
 ],
 "panels": [
  {
   "name": "dialog",
   "file": "ui-panel-dialog.png",
   "slice": [
    14,
    15,
    13,
    15
   ],
   "size": [
    225,
    203
   ]
  },
  {
   "name": "tooltip",
   "file": "ui-panel-tooltip.png",
   "slice": [
    13,
    14,
    12,
    13
   ],
   "size": [
    168,
    133
   ]
  }
 ],
 "atlas": {
  "source": [
   1000,
   667
  ],
  "found": [
   {
    "name": "trophy",
    "box": [
     38,
     23,
     225,
     219
    ]
   },
   {
    "name": "dumbbell",
    "box": [
     266,
     53,
     505,
     201
    ]
   },
   {
    "name": "water-bottle",
    "box": [
     573,
     12,
     655,
     224
    ]
   },
   {
    "name": "towel",
    "box": [
     718,
     70,
     961,
     216
    ]
   },
   {
    "name": "boxing-glove",
    "box": [
     70,
     232,
     295,
     414
    ]
   },
   {
    "name": "jump-rope",
    "box": [
     382,
     242,
     618,
     419
    ]
   },
   {
    "name": "bell",
    "box": [
     690,
     240,
     885,
     406
    ]
   },
   {
    "name": "medal",
    "box": [
     129,
     424,
     268,
     639
    ]
   },
   {
    "name": "sneaker",
    "box": [
     357,
     441,
     633,
     621
    ]
   },
   {
    "name": "stopwatch",
    "box": [
     758,
     419,
     929,
     642
    ]
   }
  ],
  "packed": [
   {
    "name": "trophy",
    "x": 327,
    "y": 0,
    "w": 153,
    "h": 160
   },
   {
    "name": "dumbbell",
    "x": 356,
    "y": 335,
    "w": 195,
    "h": 121
   },
   {
    "name": "water-bottle",
    "x": 258,
    "y": 0,
    "w": 67,
    "h": 173
   },
   {
    "name": "towel",
    "x": 0,
    "y": 482,
    "w": 199,
    "h": 120
   },
   {
    "name": "boxing-glove",
    "x": 0,
    "y": 184,
    "w": 184,
    "h": 149
   },
   {
    "name": "jump-rope",
    "x": 0,
    "y": 335,
    "w": 193,
    "h": 145
   },
   {
    "name": "bell",
    "x": 195,
    "y": 335,
    "w": 159,
    "h": 136
   },
   {
    "name": "medal",
    "x": 142,
    "y": 0,
    "w": 114,
    "h": 175
   },
   {
    "name": "sneaker",
    "x": 186,
    "y": 184,
    "w": 225,
    "h": 147
   },
   {
    "name": "stopwatch",
    "x": 0,
    "y": 0,
    "w": 140,
    "h": 182
   }
  ],
  "size": [
   551,
   602
  ]
 },
 "healthy": {
  "before": [
   {
    "id": "frames",
    "status": "fail",
    "detail": "missing frame(s) [2]",
    "frames": [
     2
    ]
   },
   {
    "id": "source-edge",
    "status": "warn",
    "detail": "subject touches the source image edge in frame(s) [6]; it may be cut off",
    "frames": [
     6
    ]
   },
   {
    "id": "specks",
    "status": "pass",
    "detail": "no stray specks",
    "frames": []
   },
   {
    "id": "scale",
    "status": "warn",
    "detail": "frame(s) drawn at another size than the row (3: -25%); repair them",
    "frames": [
     3
    ]
   },
   {
    "id": "color",
    "status": "warn",
    "detail": "frame(s) [4] differ in color or lighting from the rest (max difference 27.2); repair them",
    "frames": [
     4
    ]
   },
   {
    "id": "identity",
    "status": "warn",
    "detail": "palette differs from the anchor in frame(s) [4] (max distance 0.54)",
    "frames": [
     4
    ]
   },
   {
    "id": "motion",
    "status": "pass",
    "detail": "average change between frames 0.068",
    "frames": []
   },
   {
    "id": "cell-edge",
    "status": "pass",
    "detail": "every frame fits inside its cell",
    "frames": []
   }
  ],
  "after": [
   {
    "id": "frames",
    "status": "pass",
    "detail": "6 of 6 frames found",
    "frames": []
   },
   {
    "id": "source-edge",
    "status": "pass",
    "detail": "no frame touches the source image edge",
    "frames": []
   },
   {
    "id": "specks",
    "status": "pass",
    "detail": "no stray specks",
    "frames": []
   },
   {
    "id": "scale",
    "status": "pass",
    "detail": "every frame within 0% of the row's size",
    "frames": []
   },
   {
    "id": "color",
    "status": "pass",
    "detail": "color and lighting match across frames (max difference 2.4)",
    "frames": []
   },
   {
    "id": "identity",
    "status": "pass",
    "detail": "palette matches the anchor (max distance 0.22)",
    "frames": []
   },
   {
    "id": "motion",
    "status": "pass",
    "detail": "average change between frames 0.062",
    "frames": []
   },
   {
    "id": "cell-edge",
    "status": "pass",
    "detail": "every frame fits inside its cell",
    "frames": []
   }
  ]
 }
};
