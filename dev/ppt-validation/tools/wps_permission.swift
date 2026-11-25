import ApplicationServices
import Foundation

let prompt = [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary
let trusted = AXIsProcessTrustedWithOptions(prompt)
print("bundle=\(Bundle.main.bundleIdentifier ?? "none")")
print("accessibility=\(trusted)")
