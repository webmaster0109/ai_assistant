
async function deleteSession(sessionId) {
  try {
    const response = await fetch(`chat/delete/${sessionId}/`);
    if (!response.ok) {
      throw new Error(`Delete failed: ${response.status}`);
    }
  } catch (err) {
    console.error("[deleteSession] Failed:", err);
  }
}
