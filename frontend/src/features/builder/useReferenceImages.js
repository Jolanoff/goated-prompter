import { useState } from "react";

/** Builder reference image slots read in the browser before generation. */
export function useReferenceImages({ busy, setError }) {
  const [images, setImages] = useState([null, null, null, null]);
  const [uploading, setUploading] = useState(0);

  async function upload(file, slot) {
    if (!file || busy) return;
    if (
      !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
      file.size > 20 * 1024 * 1024
    ) {
      setError("Choose a PNG, JPG, or WEBP image no larger than 20 MiB.");
      return;
    }
    setUploading((count) => count + 1);
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("Could not read this image."));
        reader.readAsDataURL(file);
      });
      setImages((previous) =>
        previous.map((image, index) =>
          index === slot ? { data, name: file.name } : image,
        ),
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading((count) => count - 1);
    }
  }

  function remove(slot) {
    setImages((previous) => previous.map((item, index) => index === slot ? null : item));
  }

  return { images, uploading, upload, remove };
}
