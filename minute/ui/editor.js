// Notes editor: what-you-see editing over a Markdown file.
//
// The page edits rich text (contenteditable) with Markdown shortcuts; notes are stored as Markdown.
//   "- " / "* "  bullet list      "1. "  numbered list      "# " "## " "### "  headings
//   Enter continues a list, Enter on an empty item leaves it, Tab / Shift+Tab nest
//   Ctrl+B / Ctrl+I, or typing **bold** / *italic*
// Supported Markdown subset: headings, nested bullet / numbered lists, paragraphs, **bold**, *italic*, `code`.

(function () {
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // --- Markdown -> HTML ------------------------------------------------------
  function inlineToHtml(text) {
    return esc(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  }

  function mdToHtml(md) {
    const out = [];
    const stack = []; // open lists: {tag, indent}
    const closeTo = (indent) => {
      while (stack.length && stack[stack.length - 1].indent >= indent) out.push(`</li></${stack.pop().tag}>`);
    };
    for (const raw of (md || "").replace(/\r/g, "").split("\n")) {
      const item = raw.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
      if (item) {
        const indent = item[1].replace(/\t/g, "  ").length;
        const tag = /\d/.test(item[2]) ? "ol" : "ul";
        const top = stack[stack.length - 1];
        if (top && indent > top.indent) {
          out.push(`<${tag}>`);
          stack.push({ tag, indent });
        } else {
          closeTo(indent + 1);
          const same = stack[stack.length - 1];
          if (same && same.indent === indent && same.tag === tag) out.push("</li>");
          else {
            closeTo(indent);
            out.push(`<${tag}>`);
            stack.push({ tag, indent });
          }
        }
        out.push(`<li>${inlineToHtml(item[3])}`);
        continue;
      }
      closeTo(0);
      const h = raw.match(/^(#{1,3})\s+(.*)$/);
      if (h) out.push(`<h${h[1].length}>${inlineToHtml(h[2])}</h${h[1].length}>`);
      else if (raw.trim()) out.push(`<p>${inlineToHtml(raw)}</p>`);
    }
    closeTo(0);
    return out.join("");
  }

  // --- HTML -> Markdown ------------------------------------------------------
  function inlineToMd(node) {
    let s = "";
    for (const n of node.childNodes) {
      if (n.nodeType === 3) s += n.nodeValue.replace(/ /g, " ");
      else if (n.nodeType !== 1) continue;
      else if (/^(UL|OL)$/.test(n.tagName)) continue; // nested lists are handled by listToMd
      else if (n.tagName === "BR") s += "";
      else {
        const inner = inlineToMd(n);
        if (!inner.trim()) { s += inner; continue; }
        const tag = n.tagName;
        const bold = tag === "B" || tag === "STRONG" || /font-weight:\s*(bold|[6-9]00)/.test(n.getAttribute("style") || "");
        const italic = tag === "I" || tag === "EM";
        s += tag === "CODE" ? `\`${inner}\`` : bold ? `**${inner}**` : italic ? `*${inner}*` : inner;
      }
    }
    return s;
  }

  function listToMd(list, depth, lines) {
    let i = 1;
    for (const child of list.children) {
      if (child.tagName === "LI") {
        const marker = list.tagName === "OL" ? `${i++}.` : "-";
        lines.push(`${"  ".repeat(depth)}${marker} ${inlineToMd(child).trim()}`);
        for (const sub of child.children) if (/^(UL|OL)$/.test(sub.tagName)) listToMd(sub, depth + 1, lines);
      } else if (/^(UL|OL)$/.test(child.tagName)) {
        // Chromium nests an indented list as a sibling of the <li>, right where it belongs.
        listToMd(child, depth + 1, lines);
      }
    }
  }

  const BLOCK = /^(UL|OL|P|DIV|H[1-6]|BLOCKQUOTE)$/;
  const hasBlockChildren = (n) => [...n.children].some((c) => BLOCK.test(c.tagName));

  function htmlToMd(root) {
    const lines = [];
    let prevList = false;
    const walk = (parent) => {
      let inline = ""; // loose text and inline elements between blocks form one paragraph
      const flush = () => {
        const text = inline.trim();
        inline = "";
        if (!text) return;
        if (lines.length) lines.push("");
        lines.push(text);
        prevList = false;
      };
      for (const n of parent.childNodes) {
        if (n.nodeType === 3) { inline += n.nodeValue.replace(/ /g, " "); continue; }
        if (n.nodeType !== 1) continue;
        const tag = n.tagName;
        if (!BLOCK.test(tag)) { inline += inlineToMd({ childNodes: [n] }); continue; }
        flush();
        if (/^(UL|OL)$/.test(tag)) {
          if (lines.length) lines.push("");
          listToMd(n, 0, lines);
          prevList = true;
        } else if (hasBlockChildren(n)) {
          walk(n); // e.g. a list Chromium put inside a <p>
        } else {
          const text = inlineToMd(n).trim();
          if (!text) continue;
          if (lines.length) lines.push("");
          const h = tag.match(/^H([1-6])$/);
          lines.push(h ? `${"#".repeat(Math.min(3, +h[1]))} ${text}` : text);
          prevList = false;
        }
      }
      flush();
    };
    walk(root);
    return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  // Chromium sometimes nests a new list or paragraph inside a <p>; unwrap so the DOM stays flat.
  function normalize(el) {
    for (const p of [...el.querySelectorAll("p, div")]) {
      if (p !== el && hasBlockChildren(p)) {
        while (p.firstChild) p.parentNode.insertBefore(p.firstChild, p);
        p.remove();
      }
    }
  }

  // --- editing behaviour -------------------------------------------------------
  function currentBlock(el) {
    const sel = getSelection();
    if (!sel.rangeCount) return null;
    for (let n = sel.anchorNode; n && n !== el; n = n.parentNode) {
      if (n.nodeType === 1 && /^(P|DIV|H[1-6]|LI)$/.test(n.tagName)) return n;
      if (n.parentNode === el) return n; // loose text at the top level
    }
    return null;
  }

  function textBeforeCaret(block) {
    const sel = getSelection();
    const r = document.createRange();
    r.selectNodeContents(block);
    r.setEnd(sel.anchorNode, sel.anchorOffset);
    return r.toString();
  }

  function deleteBeforeCaret(count) {
    const sel = getSelection();
    for (let i = 0; i < count; i++) sel.modify("extend", "backward", "character");
    document.execCommand("delete");
  }

  const BLOCK_RULES = [
    [/^[-*+]$/, () => document.execCommand("insertUnorderedList")],
    [/^1[.)]$/, () => document.execCommand("insertOrderedList")],
    [/^###$/, () => document.execCommand("formatBlock", false, "h3")],
    [/^##$/, () => document.execCommand("formatBlock", false, "h2")],
    [/^#$/, () => document.execCommand("formatBlock", false, "h1")],
  ];

  function create(el, onChange) {
    el.contentEditable = "true";
    el.spellcheck = true;
    document.execCommand("defaultParagraphSeparator", false, "p");

    const refreshEmpty = () => el.classList.toggle("is-empty", !el.textContent.trim() && !el.querySelector("li"));
    const changed = () => { normalize(el); refreshEmpty(); onChange(htmlToMd(el)); };

    el.addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        if (currentBlock(el)?.tagName === "LI") document.execCommand(e.shiftKey ? "outdent" : "indent");
        changed();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === "b" || e.key === "i")) {
        e.preventDefault();
        document.execCommand(e.key === "b" ? "bold" : "italic");
        changed();
      } else if (e.key === " " && !e.ctrlKey) {
        const block = currentBlock(el);
        if (!block) return;
        const before = textBeforeCaret(block);
        const rule = BLOCK_RULES.find(([re]) => re.test(before));
        if (rule && block.tagName !== "LI") {
          e.preventDefault();
          deleteBeforeCaret(before.length);
          rule[1]();
          changed();
        }
      } else if (e.key === "Enter" && !e.shiftKey) {
        // After a heading, continue with a normal paragraph.
        const block = currentBlock(el);
        if (block && /^H[1-3]$/.test(block.tagName) && textBeforeCaret(block).length === block.textContent.length) {
          e.preventDefault();
          document.execCommand("insertParagraph");
          document.execCommand("formatBlock", false, "p");
          changed();
        }
      }
    });

    el.addEventListener("input", () => {
      // **bold** and *italic* typed inline
      const block = currentBlock(el);
      if (block) {
        const before = textBeforeCaret(block);
        const bold = before.match(/\*\*([^*]+)\*\*$/);
        const italic = !bold && before.match(/(?:^|[^*])\*([^*\s][^*]*)\*$/);
        const m = bold || italic;
        if (m) {
          const cmd = bold ? "bold" : "italic";
          deleteBeforeCaret(m[1].length + (bold ? 4 : 2));
          document.execCommand(cmd);
          document.execCommand("insertText", false, m[1]);
          document.execCommand(cmd); // typing after it is plain again
        }
      }
      changed();
    });

    el.addEventListener("paste", (e) => {
      // Pasted Markdown keeps its structure; anything else comes in as plain text.
      e.preventDefault();
      const text = e.clipboardData.getData("text/plain");
      if (/^(\s*([-*+]|\d+[.)])\s|#{1,3}\s)/m.test(text)) document.execCommand("insertHTML", false, mdToHtml(text));
      else document.execCommand("insertText", false, text);
      changed();
    });

    return {
      setMarkdown(md) {
        el.innerHTML = mdToHtml(md);
        refreshEmpty();
      },
      getMarkdown: () => htmlToMd(el),
      focus() {
        el.focus();
        const r = document.createRange();
        r.selectNodeContents(el);
        r.collapse(false);
        const sel = getSelection();
        sel.removeAllRanges();
        sel.addRange(r);
      },
    };
  }

  window.NoteEditor = { create, mdToHtml, htmlToMd };
})();
