"""Privacy counter shown in the UI as `face images uploaded`.

Nothing in Myrmidon increments it: no code path uploads camera frames or face images.
Frames stay in memory, are reduced to numbers (distance, eye opening, head angles,
brightness) and dropped. Bedrock only ever receives text and numbers.
"""

FACE_IMAGES_UPLOADED = 0
