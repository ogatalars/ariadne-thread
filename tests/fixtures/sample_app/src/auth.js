const crypto = require("crypto");

function hashPassword(password, salt) {
  return crypto.scryptSync(password, salt, 32).toString("hex");
}

async function login(req, res) {
  const user = await findUser(req.body.email);
  if (!user || hashPassword(req.body.password, user.salt) !== user.hash) {
    return res.status(401).json({ error: "invalid credentials" });
  }
  res.json({ token: createSession(user.id) });
}

module.exports = { login, hashPassword };
