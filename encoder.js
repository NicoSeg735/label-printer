const fs = require('fs');
const path = require('path');
const sdk = require('./detong_sdk.js');

// Simple PNG reader or raw image buffer
// When called from Python, Python can pass raw RGBA buffer or PNG path.
const PROFILES = {
    // Implements the public DothanTech Bitmap Printing Command Description
    // V1.1 directly. It is retained for protocol investigation only.
    'dothan-v11': null,
    // Kept only to compare the bundled, undocumented SDK with the documented
    // protocol while diagnosing a device.
    'sdk-compact': {
        hardwareFlags: 0,
        softwareFlags: 16,
    },
    // Raw CMD_BITMAP_PRINT is useful for analysis, but has not been proven to
    // execute on this printer and creates substantially larger transfers.
    'sdk-raw': {
        enableSuperBitmap: false,
        hardwareFlags: 0,
        softwareFlags: 0,
    },
};

function packRow(rawBytes, width, y) {
    const bytesPerRow = Math.ceil(width / 8);
    const row = Buffer.alloc(bytesPerRow);
    for (let x = 0; x < width; x++) {
        const offset = (y * width + x) * 4;
        const alpha = rawBytes[offset + 3];
        const luminance = (rawBytes[offset] * 299 + rawBytes[offset + 1] * 587 + rawBytes[offset + 2] * 114) / 1000;
        if (alpha > 0 && luminance < 128) row[Math.floor(x / 8)] |= 0x80 >> (x % 8);
    }
    return row;
}

function encodeDothanV11(rawBytes, width, height, gapType, darkness, speed, pageKey) {
    const widthMm = Math.ceil(width / 8);
    if (widthMm < 1 || widthMm > 48) throw new Error(`Unsupported print width: ${width} dots`);

    // ESC @ and the bitmap commands are documented by DothanTech.  The four
    // parameter records match the vendor SDK's emitted configuration, but are
    // placed after initialization as required by the bitmap specification.
    // Bitmap rows themselves intentionally have no generic length/checksum
    // envelope.
    const output = [Buffer.from([
        0x1b, 0x40,
        0x1f, 0x20, 0x02, 0x00, pageKey, 0x88,
        0x1f, 0x27, 0x01, widthMm, 0x88,
        0x1f, 0x42, 0x01, gapType, 0x88,
        0x1f, 0x43, 0x01, Math.max(0, darkness - 1), 0x88,
        0x1f, 0x44, 0x01, Math.max(0, speed - 1), 0x88,
    ])];
    let blankRows = 0;
    let previousRow = null;
    let duplicateRows = 0;

    const flushBlankRows = () => {
        while (blankRows > 0) {
            const count = Math.min(blankRows, 255);
            output.push(Buffer.from([0x1b, 0x4a, count]));
            blankRows -= count;
        }
    };
    const flushDuplicateRows = () => {
        while (duplicateRows > 0) {
            const count = Math.min(duplicateRows, 192);
            output.push(Buffer.from([0x1f, 0x2e, count - 1]));
            duplicateRows -= count;
        }
    };

    for (let y = 0; y < height; y++) {
        const row = packRow(rawBytes, width, y);
        const first = row.findIndex(byte => byte !== 0);
        if (first === -1) {
            flushDuplicateRows();
            blankRows++;
            previousRow = null;
            continue;
        }

        flushBlankRows();
        if (previousRow && row.equals(previousRow)) {
            duplicateRows++;
            continue;
        }

        flushDuplicateRows();
        let last = row.length - 1;
        while (row[last] === 0) last--;
        const data = row.subarray(first, last + 1);
        output.push(Buffer.from([0x1f, 0x2b, first, data.length]), data);
        previousRow = row;
    }
    flushDuplicateRows();
    flushBlankRows();
    output.push(Buffer.from([0x0c]));
    return Buffer.concat(output);
}

function encodeImage(imagePath, gapType = 2, darkness = 3, speed = 3, profile = 'sdk-compact') {
    // Read JSON metadata if passed, or raw RGBA file
    const metaPath = imagePath + '.meta.json';
    const rawPath = imagePath + '.raw';

    if (fs.existsSync(metaPath) && fs.existsSync(rawPath)) {
        const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
        const rawBytes = fs.readFileSync(rawPath);
        
        const pageKey = meta.pageKey || Math.floor(Math.random() * 200) + 1;
        if (!Object.hasOwn(PROFILES, profile)) {
            throw new Error(`Unknown encoding profile: ${profile}`);
        }

        let totalBuffer;
        if (profile === 'dothan-v11') {
            totalBuffer = encodeDothanV11(
                rawBytes, meta.width, meta.height, gapType, darkness, speed, pageKey
            );
        } else {
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
            gapLength: 0,
            printDarkness: darkness,
            printSpeed: speed
            }, {
                printerDPI: 203,
                printerWidth: 384,
                ...PROFILES[profile]
            });
            totalBuffer = Buffer.concat(encoded.map(p => Buffer.from(p)));
        }

        const outPath = imagePath + '.bin';
        fs.writeFileSync(outPath, totalBuffer);
        console.log(JSON.stringify({
            success: true,
            bytes: totalBuffer.length,
            outPath,
            pageKey,
            profile,
        }));
        return;
    }

    console.error(JSON.stringify({ success: false, error: "Raw/Meta files not found" }));
}

const args = process.argv.slice(2);
if (args.length > 0) {
    encodeImage(args[0], parseInt(args[1] || 2), parseInt(args[2] || 3), parseInt(args[3] || 3), args[4] || 'sdk-compact');
}
