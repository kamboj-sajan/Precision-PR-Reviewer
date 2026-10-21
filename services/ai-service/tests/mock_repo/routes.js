const { verifyPassword } = require('./auth');
const { sanitizeInput } = require('./utils');

function handleLogin(req, res) {
    const cleanUser = sanitizeInput(req.body.username);
    const isValid = verifyPassword(req.body.storedHash, req.body.password);
    if (!isValid) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    return res.json({ success: true, user: cleanUser });
}

function handleProfile(req, res) {
    return res.json({ profile: 'active' });
}

module.exports = {
    handleLogin,
    handleProfile
};
