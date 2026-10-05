// English and French strings for the /beam page and the BeamIn panel.
// Plain ES2017 with no import/export: /beam loads it as a classic script (old
// car and TV browsers), the panel imports it for its side effect.
// Placeholders use {name}; a test keeps both languages in sync.
(function () {
  "use strict";

  var STRINGS = {
    en: {
      // /beam page
      title: "Sign in with your phone",
      loading: "Preparing a code…",
      scan: "Scan this QR code with a phone that is signed in to Home Assistant.",
      qr_alt: "QR code to approve this sign-in from your phone",
      or_code: "Or open BeamIn in Home Assistant and type this code:",
      match: "Then pick this number on your phone:",
      expires_in: "Expires in {time}",
      never_share:
        "Never send this code to anyone: only someone standing in front of this screen should approve it.",
      approved: "Approved! Signing you in…",
      denied: "The sign-in was denied on the phone.",
      denied_wrong_number:
        "A wrong number was picked on the phone, so this code was cancelled.",
      denied_local_only: "This account can only sign in from the local network.",
      expired: "This code has expired.",
      new_code: "New code",
      retry: "Try again",
      error_rate_limited: "Too many attempts. Try again in {seconds} s.",
      error_too_many_pending:
        "Too many sign-in requests are waiting. Try again in {seconds} s.",
      error_unavailable: "BeamIn is not enabled on this Home Assistant.",
      error_storage: "This browser cannot store the session (private mode or storage full).",
      error_generic: "Something went wrong. Check the connection and try again.",

      // Panel
      menu: "Menu",
      enter_title: "Approve a sign-in",
      enter_help: "On the device to sign in, open:",
      code_input: "Code shown on the device",
      continue: "Continue",
      invalid_format: "A code has 6 letters or digits, like K7F-29X.",
      review_title: "Sign-in request",
      device_reported: "As reported by the device",
      kind_car: "Car",
      kind_tv: "TV",
      kind_tablet: "Tablet",
      kind_phone: "Phone",
      kind_computer: "Computer",
      kind_unknown: "Unknown device",
      ip_address: "IP address",
      network: "Network",
      network_local: "Local network",
      network_internet: "Internet",
      network_same_public_ip: "Internet, same address as this phone",
      network_cloud: "Home Assistant Cloud",
      network_unknown: "Unknown",
      requested: "Requested",
      seconds_ago: "{seconds} s ago",
      expires: "Expires",
      in_seconds: "in {seconds} s",
      warning:
        "Only approve a screen that is physically in front of you. Never approve a code someone sent you.",
      pick_number: "Which number is shown on the device?",
      session: "Session",
      duration_normal: "This device (stays signed in)",
      duration_temporary: "Temporary ({duration})",
      sign_in_as: "Signed in as",
      you: "{name} (you)",
      another_user: "Sign in as another user",
      admin_shared_warning:
        "This is an administrator account on a shared device ({kind}). Prefer a limited account.",
      approve: "Approve",
      deny: "Deny",
      done_approved: "{device} is signing in as {user}.",
      done_denied: "Sign-in denied.",
      again: "Approve another device",
      error_invalid_code: "This code is unknown or has expired. Check the device screen.",
      error_wrong_number:
        "Wrong number: the request was cancelled. Start again on the device.",
      error_locked: "Too many wrong codes. Try again in {minutes} min.",
      error_not_interactive:
        "Approvals need a signed-in person, not a long-lived access token.",
      error_temporary_session:
        "This session is temporary and cannot approve other devices.",
      error_local_only: "This user can only sign in from the local network.",
      error_not_allowed: "You cannot sign a device in as this user.",
      error_approve_generic: "Something went wrong. Try again.",
      minutes: "{count} min",
      hours_one: "1 hour",
      hours_other: "{count} hours",
    },
    fr: {
      title: "Connexion avec votre téléphone",
      loading: "Préparation d'un code…",
      scan: "Scannez ce QR code avec un téléphone déjà connecté à Home Assistant.",
      qr_alt: "QR code pour approuver cette connexion depuis votre téléphone",
      or_code: "Ou ouvrez BeamIn dans Home Assistant et saisissez ce code :",
      match: "Puis choisissez ce numéro sur votre téléphone :",
      expires_in: "Expire dans {time}",
      never_share:
        "N'envoyez jamais ce code à quelqu'un : seule une personne devant cet écran doit l'approuver.",
      approved: "Approuvé ! Connexion en cours…",
      denied: "La connexion a été refusée sur le téléphone.",
      denied_wrong_number:
        "Un mauvais numéro a été choisi sur le téléphone : ce code est annulé.",
      denied_local_only: "Ce compte ne peut se connecter que depuis le réseau local.",
      expired: "Ce code a expiré.",
      new_code: "Nouveau code",
      retry: "Réessayer",
      error_rate_limited: "Trop de tentatives. Réessayez dans {seconds} s.",
      error_too_many_pending: "Trop de demandes en attente. Réessayez dans {seconds} s.",
      error_unavailable: "BeamIn n'est pas activé sur ce Home Assistant.",
      error_storage:
        "Ce navigateur ne peut pas enregistrer la session (navigation privée ou stockage plein).",
      error_generic: "Une erreur est survenue. Vérifiez la connexion et réessayez.",

      menu: "Menu",
      enter_title: "Approuver une connexion",
      enter_help: "Sur l'appareil à connecter, ouvrez :",
      code_input: "Code affiché sur l'appareil",
      continue: "Continuer",
      invalid_format: "Un code comporte 6 lettres ou chiffres, par exemple K7F-29X.",
      review_title: "Demande de connexion",
      device_reported: "Selon l'appareil",
      kind_car: "Voiture",
      kind_tv: "TV",
      kind_tablet: "Tablette",
      kind_phone: "Téléphone",
      kind_computer: "Ordinateur",
      kind_unknown: "Appareil inconnu",
      ip_address: "Adresse IP",
      network: "Réseau",
      network_local: "Réseau local",
      network_internet: "Internet",
      network_same_public_ip: "Internet, même adresse que ce téléphone",
      network_cloud: "Home Assistant Cloud",
      network_unknown: "Inconnu",
      requested: "Demandé",
      seconds_ago: "il y a {seconds} s",
      expires: "Expire",
      in_seconds: "dans {seconds} s",
      warning:
        "N'approuvez qu'un écran physiquement devant vous. N'approuvez jamais un code qu'on vous a envoyé.",
      pick_number: "Quel numéro est affiché sur l'appareil ?",
      session: "Session",
      duration_normal: "Cet appareil (reste connecté)",
      duration_temporary: "Temporaire ({duration})",
      sign_in_as: "Connexion en tant que",
      you: "{name} (vous)",
      another_user: "Se connecter en tant qu'un autre utilisateur",
      admin_shared_warning:
        "Compte administrateur sur un appareil partagé ({kind}). Préférez un compte limité.",
      approve: "Approuver",
      deny: "Refuser",
      done_approved: "{device} se connecte en tant que {user}.",
      done_denied: "Connexion refusée.",
      again: "Approuver un autre appareil",
      error_invalid_code: "Ce code est inconnu ou a expiré. Vérifiez l'écran de l'appareil.",
      error_wrong_number:
        "Mauvais numéro : la demande est annulée. Recommencez sur l'appareil.",
      error_locked: "Trop de codes erronés. Réessayez dans {minutes} min.",
      error_not_interactive:
        "L'approbation demande une personne connectée, pas un jeton d'accès longue durée.",
      error_temporary_session:
        "Cette session est temporaire et ne peut pas approuver d'autres appareils.",
      error_local_only: "Cet utilisateur ne peut se connecter que depuis le réseau local.",
      error_not_allowed: "Vous ne pouvez pas connecter un appareil avec cet utilisateur.",
      error_approve_generic: "Une erreur est survenue. Réessayez.",
      minutes: "{count} min",
      hours_one: "1 heure",
      hours_other: "{count} heures",
    },
  };

  function has(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  function pickLanguage(candidates) {
    for (var i = 0; i < candidates.length; i++) {
      var base = String(candidates[i] || "").toLowerCase().split(/[-_]/)[0];
      if (has(STRINGS, base)) return base;
    }
    return "en";
  }

  function createTranslator(candidates) {
    var language = pickLanguage(candidates);
    var strings = STRINGS[language];
    function t(key, params) {
      var values = params || {};
      var text = has(strings, key) ? strings[key] : has(STRINGS.en, key) ? STRINGS.en[key] : key;
      return text.replace(/\{(\w+)\}/g, function (match, name) {
        return has(values, name) ? String(values[name]) : match;
      });
    }
    return { language: language, t: t };
  }

  function formatDuration(t, minutes) {
    if (minutes % 60 !== 0) return t("minutes", { count: minutes });
    var hours = minutes / 60;
    return hours === 1 ? t("hours_one") : t("hours_other", { count: hours });
  }

  self.BeamInI18n = {
    STRINGS: STRINGS,
    pickLanguage: pickLanguage,
    createTranslator: createTranslator,
    formatDuration: formatDuration,
  };
})();
