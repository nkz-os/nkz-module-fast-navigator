/** Navigates inside the host through the SDK, with a plain location change when the SDK is not there. */
export function navigateTo(path: string): void {
  const sdk = (window as unknown as { __NKZ_SDK__?: { navigate?: (p: string) => void } }).__NKZ_SDK__;
  if (sdk?.navigate) {
    sdk.navigate(path);
    return;
  }
  window.location.assign(path);
}
