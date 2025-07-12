"use strict";
/*
 * ATTENTION: An "eval-source-map" devtool has been used.
 * This devtool is neither made for production nor for readable output files.
 * It uses "eval()" calls to create a separate source file with attached SourceMaps in the browser devtools.
 * If you are trying to read the output file, select a different devtool (https://webpack.js.org/configuration/devtool/)
 * or disable the default devtool with "devtool: false".
 * If you are looking for production-ready output files, see mode: "production" (https://webpack.js.org/configuration/mode/).
 */
(() => {
var exports = {};
exports.id = "pages/_document";
exports.ids = ["pages/_document"];
exports.modules = {

/***/ "(pages-dir-node)/./pages/_document.js":
/*!****************************!*\
  !*** ./pages/_document.js ***!
  \****************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

eval("__webpack_require__.r(__webpack_exports__);\n/* harmony export */ __webpack_require__.d(__webpack_exports__, {\n/* harmony export */   \"default\": () => (/* binding */ Document)\n/* harmony export */ });\n/* harmony import */ var next_document__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! next/document */ \"(pages-dir-node)/./node_modules/next/document.js\");\n/* harmony import */ var next_document__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(next_document__WEBPACK_IMPORTED_MODULE_0__);\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! react/jsx-dev-runtime */ \"react/jsx-dev-runtime\");\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_1__);\nvar _jsxFileName = \"C:\\\\shadow_market\\\\frontend\\\\pages\\\\_document.js\";\nfunction ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }\nfunction _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }\nfunction _defineProperty(obj, key, value) { key = _toPropertyKey(key); if (key in obj) { Object.defineProperty(obj, key, { value: value, enumerable: true, configurable: true, writable: true }); } else { obj[key] = value; } return obj; }\nfunction _toPropertyKey(arg) { var key = _toPrimitive(arg, \"string\"); return typeof key === \"symbol\" ? key : String(key); }\nfunction _toPrimitive(input, hint) { if (typeof input !== \"object\" || input === null) return input; var prim = input[Symbol.toPrimitive]; if (prim !== undefined) { var res = prim.call(input, hint || \"default\"); if (typeof res !== \"object\") return res; throw new TypeError(\"@@toPrimitive must return a primitive value.\"); } return (hint === \"string\" ? String : Number)(input); }\n// frontend/pages/_document.js\n// /***************************************************************************************\n// * REVISION HISTORY (Most recent first)\n// ***************************************************************************************\n// * 2025-04-28    [Gemini]   Modified for CSP Nonce implementation.\n// * - Added getInitialProps to read X-CSP-Nonce header from request.\n// * - Passed nonce as prop to Document component.\n// * - Applied nonce prop to NextScript component.\n// * 2025-04-28    [Gemini]   Initial creation. Standard Next.js custom Document boilerplate.\n// ***************************************************************************************/\n\n\n\nfunction Document({\n  cspNonce\n}) {\n  // Receive nonce as prop\n  return /*#__PURE__*/(0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_1__.jsxDEV)(next_document__WEBPACK_IMPORTED_MODULE_0__.Html, {\n    lang: \"en\",\n    children: [/*#__PURE__*/(0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_1__.jsxDEV)(next_document__WEBPACK_IMPORTED_MODULE_0__.Head, {\n      children: \" \"\n    }, void 0, false, {\n      fileName: _jsxFileName,\n      lineNumber: 17,\n      columnNumber: 7\n    }, this), /*#__PURE__*/(0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_1__.jsxDEV)(\"body\", {\n      children: [/*#__PURE__*/(0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_1__.jsxDEV)(next_document__WEBPACK_IMPORTED_MODULE_0__.Main, {}, void 0, false, {\n        fileName: _jsxFileName,\n        lineNumber: 22,\n        columnNumber: 9\n      }, this), /*#__PURE__*/(0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_1__.jsxDEV)(next_document__WEBPACK_IMPORTED_MODULE_0__.NextScript, {\n        nonce: cspNonce\n      }, void 0, false, {\n        fileName: _jsxFileName,\n        lineNumber: 23,\n        columnNumber: 9\n      }, this), \" \"]\n    }, void 0, true, {\n      fileName: _jsxFileName,\n      lineNumber: 21,\n      columnNumber: 7\n    }, this)]\n  }, void 0, true, {\n    fileName: _jsxFileName,\n    lineNumber: 16,\n    columnNumber: 5\n  }, this);\n}\n\n// Fetch nonce from request headers during SSR/getInitialProps\nDocument.getInitialProps = async ctx => {\n  const initialProps = await ctx.defaultGetInitialProps(ctx);\n  // Read nonce from the custom header set in middleware.js\n  const cspNonce = ctx.req?.headers['x-csp-nonce'] || null;\n  return _objectSpread(_objectSpread({}, initialProps), {}, {\n    cspNonce // Pass nonce as a prop\n  });\n};//# sourceURL=[module]\n//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiKHBhZ2VzLWRpci1ub2RlKS8uL3BhZ2VzL19kb2N1bWVudC5qcyIsIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7OztBQUFBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBOztBQUU2RDtBQUFBO0FBRTlDLFNBQVNNLFFBQVFBLENBQUM7RUFBRUM7QUFBUyxDQUFDLEVBQUU7RUFBRTtFQUMvQyxvQkFDRUYsNkRBQUEsQ0FBQ0wsK0NBQUk7SUFBQ1EsSUFBSSxFQUFDLElBQUk7SUFBQUMsUUFBQSxnQkFDYkosNkRBQUEsQ0FBQ0osK0NBQUk7TUFBQVEsUUFBQSxFQUVrRDtJQUFDO01BQUFDLFFBQUEsRUFBQUMsWUFBQTtNQUFBQyxVQUFBO01BQUFDLFlBQUE7SUFBQSxPQUNsRCxDQUFDLGVBQ1BSLDZEQUFBO01BQUFJLFFBQUEsZ0JBQ0VKLDZEQUFBLENBQUNILCtDQUFJO1FBQUFRLFFBQUEsRUFBQUMsWUFBQTtRQUFBQyxVQUFBO1FBQUFDLFlBQUE7TUFBQSxPQUFFLENBQUMsZUFDUlIsNkRBQUEsQ0FBQ0YscURBQVU7UUFBQ1csS0FBSyxFQUFFUDtNQUFTO1FBQUFHLFFBQUEsRUFBQUMsWUFBQTtRQUFBQyxVQUFBO1FBQUFDLFlBQUE7TUFBQSxPQUFFLENBQUMsS0FBQztJQUFBO01BQUFILFFBQUEsRUFBQUMsWUFBQTtNQUFBQyxVQUFBO01BQUFDLFlBQUE7SUFBQSxPQUM1QixDQUFDO0VBQUE7SUFBQUgsUUFBQSxFQUFBQyxZQUFBO0lBQUFDLFVBQUE7SUFBQUMsWUFBQTtFQUFBLE9BQ0gsQ0FBQztBQUVYOztBQUVBO0FBQ0FQLFFBQVEsQ0FBQ1MsZUFBZSxHQUFHLE1BQU9DLEdBQUcsSUFBSztFQUN4QyxNQUFNQyxZQUFZLEdBQUcsTUFBTUQsR0FBRyxDQUFDRSxzQkFBc0IsQ0FBQ0YsR0FBRyxDQUFDO0VBQzFEO0VBQ0EsTUFBTVQsUUFBUSxHQUFHUyxHQUFHLENBQUNHLEdBQUcsRUFBRUMsT0FBTyxDQUFDLGFBQWEsQ0FBQyxJQUFJLElBQUk7RUFDeEQsT0FBQUMsYUFBQSxDQUFBQSxhQUFBLEtBQ0tKLFlBQVk7SUFDZlYsUUFBUSxDQUFFO0VBQUE7QUFFZCxDQUFDIiwic291cmNlcyI6WyJDOlxcc2hhZG93X21hcmtldFxcZnJvbnRlbmRcXHBhZ2VzXFxfZG9jdW1lbnQuanMiXSwic291cmNlc0NvbnRlbnQiOlsiLy8gZnJvbnRlbmQvcGFnZXMvX2RvY3VtZW50LmpzXHJcbi8vIC8qKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKipcclxuLy8gKiBSRVZJU0lPTiBISVNUT1JZIChNb3N0IHJlY2VudCBmaXJzdClcclxuLy8gKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqXHJcbi8vICogMjAyNS0wNC0yOCAgICBbR2VtaW5pXSAgIE1vZGlmaWVkIGZvciBDU1AgTm9uY2UgaW1wbGVtZW50YXRpb24uXHJcbi8vICogLSBBZGRlZCBnZXRJbml0aWFsUHJvcHMgdG8gcmVhZCBYLUNTUC1Ob25jZSBoZWFkZXIgZnJvbSByZXF1ZXN0LlxyXG4vLyAqIC0gUGFzc2VkIG5vbmNlIGFzIHByb3AgdG8gRG9jdW1lbnQgY29tcG9uZW50LlxyXG4vLyAqIC0gQXBwbGllZCBub25jZSBwcm9wIHRvIE5leHRTY3JpcHQgY29tcG9uZW50LlxyXG4vLyAqIDIwMjUtMDQtMjggICAgW0dlbWluaV0gICBJbml0aWFsIGNyZWF0aW9uLiBTdGFuZGFyZCBOZXh0LmpzIGN1c3RvbSBEb2N1bWVudCBib2lsZXJwbGF0ZS5cclxuLy8gKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKioqL1xyXG5cclxuaW1wb3J0IHsgSHRtbCwgSGVhZCwgTWFpbiwgTmV4dFNjcmlwdCB9IGZyb20gJ25leHQvZG9jdW1lbnQnO1xyXG5cclxuZXhwb3J0IGRlZmF1bHQgZnVuY3Rpb24gRG9jdW1lbnQoeyBjc3BOb25jZSB9KSB7IC8vIFJlY2VpdmUgbm9uY2UgYXMgcHJvcFxyXG4gIHJldHVybiAoXHJcbiAgICA8SHRtbCBsYW5nPVwiZW5cIj5cclxuICAgICAgPEhlYWQ+XHJcbiAgICAgICAgey8qIE5vbmNlIGFwcGxpZWQgYXV0b21hdGljYWxseSBieSBOZXh0LmpzIHRvIDxIZWFkPiBlbGVtZW50cyBpZiBuZWVkZWQgKi99XHJcbiAgICAgICAgey8qIDxtZXRhIG5hbWU9XCJjc3Atbm9uY2VcIiBjb250ZW50PXtjc3BOb25jZX0gLz4gICovfSB7LyogQWx0ZXJuYXRpdmUgd2F5IHRvIHBhc3Mgbm9uY2UgaWYgbmVlZGVkICovfVxyXG4gICAgICA8L0hlYWQ+XHJcbiAgICAgIDxib2R5PlxyXG4gICAgICAgIDxNYWluIC8+XHJcbiAgICAgICAgPE5leHRTY3JpcHQgbm9uY2U9e2NzcE5vbmNlfSAvPiB7LyogQXBwbHkgbm9uY2UgdG8gTmV4dFNjcmlwdCAqL31cclxuICAgICAgPC9ib2R5PlxyXG4gICAgPC9IdG1sPlxyXG4gICk7XHJcbn1cclxuXHJcbi8vIEZldGNoIG5vbmNlIGZyb20gcmVxdWVzdCBoZWFkZXJzIGR1cmluZyBTU1IvZ2V0SW5pdGlhbFByb3BzXHJcbkRvY3VtZW50LmdldEluaXRpYWxQcm9wcyA9IGFzeW5jIChjdHgpID0+IHtcclxuICBjb25zdCBpbml0aWFsUHJvcHMgPSBhd2FpdCBjdHguZGVmYXVsdEdldEluaXRpYWxQcm9wcyhjdHgpO1xyXG4gIC8vIFJlYWQgbm9uY2UgZnJvbSB0aGUgY3VzdG9tIGhlYWRlciBzZXQgaW4gbWlkZGxld2FyZS5qc1xyXG4gIGNvbnN0IGNzcE5vbmNlID0gY3R4LnJlcT8uaGVhZGVyc1sneC1jc3Atbm9uY2UnXSB8fCBudWxsO1xyXG4gIHJldHVybiB7XHJcbiAgICAuLi5pbml0aWFsUHJvcHMsXHJcbiAgICBjc3BOb25jZSwgLy8gUGFzcyBub25jZSBhcyBhIHByb3BcclxuICB9O1xyXG59OyJdLCJuYW1lcyI6WyJIdG1sIiwiSGVhZCIsIk1haW4iLCJOZXh0U2NyaXB0IiwianN4REVWIiwiX2pzeERFViIsIkRvY3VtZW50IiwiY3NwTm9uY2UiLCJsYW5nIiwiY2hpbGRyZW4iLCJmaWxlTmFtZSIsIl9qc3hGaWxlTmFtZSIsImxpbmVOdW1iZXIiLCJjb2x1bW5OdW1iZXIiLCJub25jZSIsImdldEluaXRpYWxQcm9wcyIsImN0eCIsImluaXRpYWxQcm9wcyIsImRlZmF1bHRHZXRJbml0aWFsUHJvcHMiLCJyZXEiLCJoZWFkZXJzIiwiX29iamVjdFNwcmVhZCJdLCJpZ25vcmVMaXN0IjpbXSwic291cmNlUm9vdCI6IiJ9\n//# sourceURL=webpack-internal:///(pages-dir-node)/./pages/_document.js\n");

/***/ }),

/***/ "@opentelemetry/api":
/*!*************************************!*\
  !*** external "@opentelemetry/api" ***!
  \*************************************/
/***/ ((module) => {

module.exports = require("@opentelemetry/api");

/***/ }),

/***/ "next/dist/compiled/next-server/pages.runtime.dev.js":
/*!**********************************************************************!*\
  !*** external "next/dist/compiled/next-server/pages.runtime.dev.js" ***!
  \**********************************************************************/
/***/ ((module) => {

module.exports = require("next/dist/compiled/next-server/pages.runtime.dev.js");

/***/ }),

/***/ "path":
/*!***********************!*\
  !*** external "path" ***!
  \***********************/
/***/ ((module) => {

module.exports = require("path");

/***/ }),

/***/ "react":
/*!************************!*\
  !*** external "react" ***!
  \************************/
/***/ ((module) => {

module.exports = require("react");

/***/ }),

/***/ "react/jsx-dev-runtime":
/*!****************************************!*\
  !*** external "react/jsx-dev-runtime" ***!
  \****************************************/
/***/ ((module) => {

module.exports = require("react/jsx-dev-runtime");

/***/ }),

/***/ "react/jsx-runtime":
/*!************************************!*\
  !*** external "react/jsx-runtime" ***!
  \************************************/
/***/ ((module) => {

module.exports = require("react/jsx-runtime");

/***/ })

};
;

// load runtime
var __webpack_require__ = require("../webpack-runtime.js");
__webpack_require__.C(exports);
var __webpack_exec__ = (moduleId) => (__webpack_require__(__webpack_require__.s = moduleId))
var __webpack_exports__ = __webpack_require__.X(0, ["vendor-chunks/next","vendor-chunks/@swc"], () => (__webpack_exec__("(pages-dir-node)/./pages/_document.js")));
module.exports = __webpack_exports__;

})();