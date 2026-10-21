const { generateSessionToken } = require('./utils');

function verifyPassword(storedPassword, candidatePassword) {
    // Vulnerable string comparison
    return storedPassword === candidatePassword;
}

function logoutUser(sessionToken) {
    return true;
}

module.exports = {
    verifyPassword,
    logoutUser
};
