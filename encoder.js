const fs = require('fs');
const path = require('path');
const sdk = require('./detong_sdk.js');

// Simple PNG reader or raw image buffer
// When called from Python, Python can pass raw RGBA buffer or PNG path.
function encodeImage(imagePath, gapType = 2, darkness = 3, speed = 3) {
    // Read JSON metadata if passed, or raw RGBA file
    const metaPath = imagePath + '.meta.json';
    const rawPath = imagePath + '.raw';

    if (fs.existsSync(metaPath) && fs.existsSync(rawPath)) {
        const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
        const rawBytes = fs.readFileSync(rawPath);
        
        const pageKey = meta.pageKey || Math.floor(Math.random() * 200) + 1;
        const encoded = sdk.PrintPackage.encodeImageData({
            imageData: {
                width: meta.width,
                height: meta.height,
                data: new Uint8Array(rawBytes)
            },
            pageKey: pageKey,
            printerDPI: 203,
            printerWidth: 384,
            gapType: gapType,
            gapLength: 2,
            printDarkness: darkness,
            printSpeed: speed
        }, {
            printerDPI: 203,
            printerWidth: 384,
            hardwareFlags: 0x35244211,
            softwareFlags: 0xF0
        });

        const outPath = imagePath + '.bin';
        const bufferList = encoded.map(p => Buffer.from(p));
        const totalBuffer = Buffer.concat(bufferList);
        fs.writeFileSync(outPath, totalBuffer);
        console.log(JSON.stringify({ success: true, bytes: totalBuffer.length, outPath, pageKey }));
        return;
    }

    console.error(JSON.stringify({ success: false, error: "Raw/Meta files not found" }));
}

const args = process.argv.slice(2);
if (args.length > 0) {
    encodeImage(args[0], parseInt(args[1] || 2), parseInt(args[2] || 3), parseInt(args[3] || 3));
}
