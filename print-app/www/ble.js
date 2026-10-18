/* Finding the shop's printer and writing to it.

   Two ways in: the app's own Bluetooth (Capacitor, which is how this reaches
   an iPhone at all) and the browser's Web Bluetooth, which only exists on
   Android and desktop Chrome and is there so the same code can be tried
   without building an app first.

   iOS has no Bluetooth Classic for anyone but Apple's own partners, so a
   printer that speaks only Classic can never be driven from an iPhone. The
   printers that do work there — and that is most of the pocket thermal ones
   sold today — advertise Low Energy as well. */

/* What the common 58mm printers call their write channel. Each maker picked
   its own and none of them wrote it down, so the app tries them in turn. */
export const PRINTER_SERVICES = [
  {service: '000018f0-0000-1000-8000-00805f9b34fb', write: '00002af1-0000-1000-8000-00805f9b34fb'},
  {service: '0000ff00-0000-1000-8000-00805f9b34fb', write: '0000ff02-0000-1000-8000-00805f9b34fb'},
  {service: '0000fee7-0000-1000-8000-00805f9b34fb', write: '0000fec7-0000-1000-8000-00805f9b34fb'},
  {service: '49535343-fe7d-4ae5-8fa9-9fafd205e455', write: '49535343-8841-43f4-a8d4-ecbe34729bb3'},
  {service: 'e7810a71-73ae-499d-8c15-faa9aef0c3f2', write: 'bef8d6c9-9c21-4c9e-b632-bd58c1009f9f'},
  {service: '0000ffe0-0000-1000-8000-00805f9b34fb', write: '0000ffe1-0000-1000-8000-00805f9b34fb'},
];

const capacitor = () => window.Capacitor?.Plugins?.BluetoothLe;

export const kind = () => (capacitor() ? 'app' : (navigator.bluetooth ? 'web' : 'none'));

/* ---- the app's own Bluetooth ------------------------------------------- */
async function appScan(onFound) {
  const ble = capacitor();
  await ble.initialize();
  const found = new Map();
  await ble.requestLEScan({services: [], allowDuplicates: false}, () => {});
  const listener = await ble.addListener('onScanResult', result => {
    const name = result.device?.name;
    if (!name || found.has(result.device.deviceId)) return;
    found.set(result.device.deviceId, name);
    onFound({id: result.device.deviceId, name});
  });
  await new Promise(resolve => setTimeout(resolve, 8000));
  await ble.stopLEScan();
  await listener.remove();
}

async function appConnect(id, {timeout = 15000} = {}) {
  const ble = capacitor();
  await ble.connect({deviceId: id, timeout});
  const services = await ble.getServices({deviceId: id});
  for (const known of PRINTER_SERVICES) {
    const service = services.services?.find(item => item.uuid.toLowerCase() === known.service);
    if (!service) continue;
    /* The channel the maker documented first; only then anything writable.
       Some services carry several, and the first writable one found is not
       always the one that feeds the print head. */
    const writable = service.characteristics?.find(item => item.uuid.toLowerCase() === known.write)
      || service.characteristics?.find(item => item.properties?.writeWithoutResponse)
      || service.characteristics?.find(item => item.properties?.write);
    if (writable) {
      return {id, service: known.service, write: writable.uuid.toLowerCase(),
        // iOS drops a without-response write to a channel that does not take one.
        withoutResponse: writable.properties?.writeWithoutResponse !== false,
        withResponse: Boolean(writable.properties?.write)};
    }
  }
  await ble.disconnect({deviceId: id});
  throw new Error('เครื่องนี้ไม่มีช่องรับข้อมูลของเครื่องพิมพ์ที่รู้จัก');
}

async function appWrite(link, pieces, onProgress) {
  const ble = capacitor();
  for (let index = 0; index < pieces.length; index++) {
    await ble.writeWithoutResponse({
      deviceId: link.id, service: link.service, characteristic: link.write,
      // Native takes a hex string only; a DataView arrives as nothing.
      value: toHex(pieces[index]),
    });
    onProgress?.(index + 1, pieces.length);
  }
}

/* ---- the browser's Bluetooth, for trying it out ------------------------ */
async function webPick() {
  const device = await navigator.bluetooth.requestDevice({
    filters: PRINTER_SERVICES.map(known => ({services: [known.service]})),
    optionalServices: PRINTER_SERVICES.map(known => known.service),
  });
  const server = await device.gatt.connect();
  for (const known of PRINTER_SERVICES) {
    try {
      const service = await server.getPrimaryService(known.service);
      const characteristics = await service.getCharacteristics();
      const writable = characteristics.find(item =>
        item.properties.write || item.properties.writeWithoutResponse);
      if (writable) return {device, characteristic: writable, name: device.name};
    } catch (_) { /* this printer speaks a different one */ }
  }
  throw new Error('เครื่องนี้ไม่มีช่องรับข้อมูลของเครื่องพิมพ์ที่รู้จัก');
}

async function webWrite(link, pieces, onProgress) {
  for (let index = 0; index < pieces.length; index++) {
    if (link.characteristic.properties.writeWithoutResponse) {
      await link.characteristic.writeValueWithoutResponse(pieces[index]);
    } else {
      await link.characteristic.writeValue(pieces[index]);
    }
    onProgress?.(index + 1, pieces.length);
  }
}

function toHex(bytes) {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

export const ble = {
  kind,
  scan: onFound => (capacitor() ? appScan(onFound) : Promise.reject(
    new Error('การค้นหาเครื่องพิมพ์ใช้ได้ในแอปเท่านั้น'))),
  connect: (id, options) => appConnect(id, options),
  pick: () => webPick(),
  write: (link, pieces, onProgress) =>
    (link.characteristic ? webWrite(link, pieces, onProgress) : appWrite(link, pieces, onProgress)),
};
