/* The shop's queue of receipts waiting to be printed.

   The same two calls the desktop agent makes: take the next one, then say it
   printed. A job that is taken and never finished goes back in the queue on
   the server after a minute and a half, so a phone that locks mid-receipt
   loses nothing. */

export class Queue {
  constructor({baseUrl, shop, key}) {
    this.base = String(baseUrl || '').replace(/\/+$/, '');
    this.shop = shop;
    this.key = key;
  }

  async call(path, body) {
    const url = `${this.base}${path}${path.includes('?') ? '&' : '?'}shop=${encodeURIComponent(this.shop)}`;
    const response = await fetch(url, {
      method: body ? 'POST' : 'GET',
      headers: {'X-Print-Key': this.key, ...(body ? {'Content-Type': 'application/json'} : {})},
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.detail || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  next() { return this.call('/api/print/next').then(data => data.job); }

  done(jobId) { return this.call('/api/print/done', {job_id: jobId}); }
}
