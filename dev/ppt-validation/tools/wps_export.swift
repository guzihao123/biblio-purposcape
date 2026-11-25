import AppKit
import ApplicationServices
import Foundation

func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(element, name as CFString, &value)
    return result == .success ? value : nil
}

func children(_ element: AXUIElement, _ name: String = kAXChildrenAttribute) -> [AXUIElement] {
    return (attribute(element, name) as? [AXUIElement]) ?? []
}

func title(_ element: AXUIElement) -> String {
    return (attribute(element, kAXTitleAttribute) as? String) ?? ""
}

func press(_ element: AXUIElement) -> Bool {
    return AXUIElementPerformAction(element, kAXPressAction as CFString) == .success
}

func pressReturn() {
    let source = CGEventSource(stateID: .combinedSessionState)
    let down = CGEvent(keyboardEventSource: source, virtualKey: 36, keyDown: true)
    let up = CGEvent(keyboardEventSource: source, virtualKey: 36, keyDown: false)
    down?.post(tap: .cghidEventTap)
    up?.post(tap: .cghidEventTap)
}

func dumpElement(_ element: AXUIElement, _ depth: Int = 0) {
    let role = (attribute(element, kAXRoleAttribute) as? String) ?? ""
    let name = title(element)
    let description = (attribute(element, kAXDescriptionAttribute) as? String) ?? ""
    let value = (attribute(element, kAXValueAttribute) as? String) ?? ""
    print("\(String(repeating: "  ", count: depth))role=\(role) title=\(name) description=\(description) value=\(value)")
    if depth < 7 {
        for child in children(element) { dumpElement(child, depth + 1) }
    }
}

let expectedPDF = URL(fileURLWithPath: CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : FileManager.default.currentDirectoryPath + "/肝细胞癌免疫治疗耐药机制组会汇报.pdf")
guard AXIsProcessTrusted() else {
    print("accessibility=false")
    exit(2)
}
guard let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.kingsoft.wpsoffice.mac").first else {
    print("WPS is not running")
    exit(2)
}
running.activate(options: [.activateAllWindows])
Thread.sleep(forTimeInterval: 1)
let app = AXUIElementCreateApplication(running.processIdentifier)
if CommandLine.arguments.contains("--inspect") {
    for window in children(app, kAXWindowsAttribute) {
        print("window=\(title(window))")
        if title(window).replacingOccurrences(of: " ", with: "") == "输出为PDF" {
            dumpElement(window)
            if let defaultValue = attribute(window, kAXDefaultButtonAttribute) {
                let button = defaultValue as! AXUIElement
                print("default_button=\(title(button))")
            }
        }
    }
    exit(0)
}
guard let menuBarValue = attribute(app, kAXMenuBarAttribute) else {
    print("WPS menu bar unavailable")
    exit(3)
}
let menuBar = menuBarValue as! AXUIElement
let menuItems = children(menuBar)
print("menus=" + menuItems.map(title).joined(separator: "|"))
guard let fileItem = menuItems.first(where: { title($0) == "文件" }), press(fileItem) else {
    print("File menu unavailable")
    exit(3)
}
Thread.sleep(forTimeInterval: 0.5)
let fileMenus = children(fileItem)
let fileActions = fileMenus.flatMap { children($0) }
print("file_actions=" + fileActions.map(title).joined(separator: "|"))
guard let exportItem = fileActions.first(where: { title($0).replacingOccurrences(of: " ", with: "").contains("输出为PDF") }) else {
    print("PDF export menu item unavailable")
    exit(3)
}
guard press(exportItem) else {
    print("PDF export menu item could not be pressed")
    exit(3)
}

var exportWindow: AXUIElement?
for _ in 0..<30 {
    for window in children(app, kAXWindowsAttribute) {
        if title(window).replacingOccurrences(of: " ", with: "") == "输出为PDF" {
            exportWindow = window
            break
        }
        if exportWindow != nil { break }
    }
    if exportWindow != nil { break }
    Thread.sleep(forTimeInterval: 0.25)
}
guard exportWindow != nil else {
    print("PDF export dialog not found")
    exit(4)
}
Thread.sleep(forTimeInterval: 1)
if let defaultValue = attribute(exportWindow!, kAXDefaultButtonAttribute) {
    let button = defaultValue as! AXUIElement
    print("pressing_default_button=\(title(button))")
    if !press(button) { pressReturn() }
} else {
    pressReturn()
}
for _ in 0..<120 {
    if FileManager.default.fileExists(atPath: expectedPDF.path) {
        print("pdf=\(expectedPDF.path)")
        exit(0)
    }
    Thread.sleep(forTimeInterval: 0.5)
}
print("PDF was not created at \(expectedPDF.path)")
exit(5)
