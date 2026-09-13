import AppKit
let out = CommandLine.arguments[1]
try FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
for size in [16,32,64,128,256,512,1024] {
 let image = NSImage(size: NSSize(width:size,height:size))
 image.lockFocus()
 let s = CGFloat(size)
 NSColor(calibratedRed:0.16,green:0.39,blue:0.91,alpha:1).setFill()
 NSBezierPath(roundedRect:NSRect(x:s*0.06,y:s*0.06,width:s*0.88,height:s*0.88),xRadius:s*0.2,yRadius:s*0.2).fill()
 NSColor.white.setStroke()
 for (i,h) in [0.20,0.36,0.54,0.30,0.44].enumerated() {
  let line = NSBezierPath(); line.lineWidth=s*0.045; line.lineCapStyle = .round
  let x = s*(0.30+Double(i)*0.1)
  line.move(to:NSPoint(x:x,y:s*(0.5-h/2)));line.line(to:NSPoint(x:x,y:s*(0.5+h/2)));line.stroke()
 }
 image.unlockFocus()
 let rep=NSBitmapImageRep(data:image.tiffRepresentation!)!
 let png=rep.representation(using:.png,properties:[:])!
 let name = size == 1024 ? "icon_512x512@2x.png" : "icon_\(size)x\(size).png"
 try png.write(to:URL(fileURLWithPath:out+"/"+name))
 if size >= 32 {try png.write(to:URL(fileURLWithPath:out+"/icon_\(size/2)x\(size/2)@2x.png"))}
}
