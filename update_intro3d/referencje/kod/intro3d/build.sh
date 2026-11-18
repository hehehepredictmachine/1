npx esbuild src/intro.js --bundle --format=iife --minify --loader:.gz=binary --outfile=dist/intro3d.js 2>&1 | grep -iv "^$" | grep -v "Done\|dist/intro3d"
