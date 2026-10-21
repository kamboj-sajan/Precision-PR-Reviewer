function sanitizeInput(inputString) {
    if (!inputString) return '';
    return inputString.trim().replace(/<[^>]*>?/gm, '');
}

function generateSessionToken(userId) {
    return 'token_' + userId + '_' + Date.now();
}

module.exports = {
    sanitizeInput,
    generateSessionToken
};
