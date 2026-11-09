// Close and resync slow consumers instead of accumulating unbounded send buffers.
export function relayFrame(browser, data, binary, limit = 1_048_576) {
  if (browser.readyState !== 1) return false;
  const bytes = Array.isArray(data)
    ? data.reduce((sum, part) => sum + part.byteLength, 0)
    : data.byteLength;
  if (browser.bufferedAmount + bytes > limit) {
    browser.close(1013, "Slow consumer; reconnect to resync");
    return false;
  }
  browser.send(data, { binary });
  return true;
}
