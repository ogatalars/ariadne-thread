class Cart {
  constructor() { this.items = []; }
  add(item) { this.items.push(item); }
  total() { return this.items.reduce((s, i) => s + i.price, 0); }
}
module.exports = { Cart };
