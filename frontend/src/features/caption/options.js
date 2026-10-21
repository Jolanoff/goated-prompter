export const targets = ["Krea 2"];
export const lengths = [["focused", "Main subject or action"], ["detailed", "Whole image"]];
export const loraTypes = [["character", "Character"], ["style", "Style"], ["action", "Action"]];
export const sources = [
  ["vision", "Describe with AI", "A vision model looks at each image and writes a caption in your words."],
  ["metadata", "Read prompt from image", "Copies the prompt saved inside each generated image (for example by ComfyUI). No model needed."],
];
