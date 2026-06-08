from __future__ import annotations

from typing import Any, Dict, Tuple


ShotTuple = Tuple[str, str, str]


# Generated from C:/Users/HAVI GROUP/Downloads/HAVI_Shot_Types_All_Products ok.xlsx.
# Keep only active workbook rows; rows marked '(inactive)' are intentionally omitted.
PRODUCT_SHOT_RULE_PRIORITY: Tuple[str, ...] = ('wedding_pillowcase',
 'baby_pillowcase',
 'linen_pillowcase',
 'ring_bearer_pillow',
 'hoops_with_photos',
 'wedding_hoop',
 'bride_handkerchief',
 'vows_book',
 'guest_book',
 'bouquet_ribbon',
 'drawstring_bag',
 'banner',
 'crown',
 'fabric_cross',
 'dress_baby',
 'plush')


PRODUCT_SHOT_RULES: Dict[str, Dict[str, Any]] = {'plush': {'display_name': 'Gấu bông',
           'aliases': ('Gấu bông',
                       'gau bong',
                       'gaubong',
                       'teddy bear',
                       'stuffed bear',
                       'stuffed toy',
                       'plush toy',
                       'plush'),
           'lock': 'the main product must remain the same soft plush/stuffed toy with the exact silhouette, fabric '
                   'pile, seams, face/features, embroidered name or motif placement, proportions, and cuddly scale '
                   'from the source image',
           'shots': (('Product display',
                      'Product display',
                      'Product photos of stuffed animals are taken from reference images. Three stuffed animals are '
                      "placed on a clean, light-colored oak table, decorated with a few children's toys (each stuffed "
                      'animal is embroidered with a different English name). Soft natural light shines from the window '
                      'above and to the left, the background is a minimalist, slightly blurred cream color, the '
                      'objects are centered with ample space, and the shallow depth of field creates a gentle bokeh '
                      'effect. A standout product photo on Etsy. \n'
                      '\n'
                      'IMPORTANT: Maintain the EXACT shape of the stuffed animals from the reference image. Keep the '
                      'fabric, color palette, facial features, embroidery details, and proportions. Do not edit the '
                      'animals themselves – only create a new background around them. \n'
                      '\n'
                      "STYLE: Handmade product photography, soft natural lighting, editorial quality, Etsy's modern "
                      'minimalist aesthetic, 1:1 square aspect ratio. \n'
                      '\n'
                      'AVOID: the appearance of the product. Mass production, studio lighting, overly harsh '
                      'background, clutter, errors. AI, text overlays, watermarks.'),
                     ('Lifestyle',
                      'Baby hug',
                      "Lifestyle photography: a baby's small hands and arms dressed in a soft cream knit romper, "
                      'gently holding the stuffed animal from the reference image close to their chest. CRITICAL: NO '
                      "face or head visible — frame must be cropped at the baby's shoulders/collar level, showing only "
                      'the torso area and small hands wrapped tenderly around the bear. Soft morning window light, '
                      "creamy warm neutral tones, emotional intimate warmth, slight motion in baby's fingers.\n"
                      '\n'
                      'IMPORTANT: Maintain the EXACT appearance of the stuffed animal from the reference image. Keep '
                      'identical fabric texture, color palette, facial features, embroidered details, and proportions. '
                      'Do not modify the animal itself — only create the new scene around it.\n'
                      '\n'
                      'STYLE: Artisan handcrafted product photography, soft natural lighting, editorial quality, '
                      'minimal modern Etsy aesthetic, 1:1 square aspect ratio. \n'
                      'AVOID: plush mass-produced look, harsh studio lighting, cluttered backgrounds, AI artifacts, '
                      'text overlays, watermarks, any visible baby face or facial features.'),
                     ('Lifestyle',
                      'Baby sleep',
                      'A lifestyle shot from a slightly elevated angle: a baby sleeping soundly on a soft '
                      "cream-colored linen blanket, cuddling a stuffed animal. Both the baby's face and the teddy bear "
                      'are visible. Soft, dreamy morning light filters through the thin curtains, creating a gentle '
                      'pastel tone and a peaceful, tranquil atmosphere.\n'
                      '\n'
                      'IMPORTANT: Maintain the EXACT shape of the stuffed animal from the reference photo. Keep the '
                      'fabric, color palette, facial features, embroidery details, and proportions unchanged. Do not '
                      'edit the animal itself—only create a new setting around it.\n'
                      '\n'
                      'STYLE: Handmade product photography, soft natural light, editorial quality, modern minimalist '
                      'Etsy-style aesthetic, 1:1 square aspect ratio. AVOID: mass-produced luxury look, harsh studio '
                      "lighting, cluttered background, AI errors, text overlays, watermarks, any baby's face or facial "
                      'features clearly visible.'),
                     ('Lifestyle',
                      'Mẹ & bé trên sofa',
                      'Lifestyle photo: A mother and child sit on a sofa, the mother holding the child in her lap, the '
                      "baby's face turned outwards, in a bright, cozy nursery or in a softly lit home, while the baby "
                      'smiles, clutching the stuffed animal from the reference image to their chest. The stuffed '
                      "animal should look small and cute in the baby's arms, with compact dimensions of approximately "
                      "50 x 27 x 14 cm, clearly proportionate to the baby. The mother's presence should convey warmth "
                      'and protection, with only her upper body and arms visible, keeping the emotional focus on the '
                      'bond between mother, baby, and the stuffed animal. Soft natural light from the window, warm '
                      'neutral tones, a minimalist, clean background with soft fabric, and a shallow depth of field '
                      'create a gentle blurring effect, giving the feeling of a delicate handcrafted keepsake – a '
                      'high-end lifestyle photo for Etsy.\n'
                      '\n'
                      'IMPORTANT: Maintain the EXACT shape of the stuffed animal from the reference image. Preserve '
                      'the original fabric, color palette, facial features, embroidery details, proportions, and '
                      'craftsmanship. Do not edit the stuffed animal in any way – only create a new context around it. '
                      'The stuffed animal must always be clearly visible. Easily recognizable and small enough to look '
                      'natural, as if being held by a baby.\n'
                      '\n'
                      'STYLE: Handmade product photography in a lifestyle style, soft natural lighting, editorial '
                      'quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                      '\n'
                      'AVOID: Harsh studio lighting, cluttered backgrounds, unrealistic mother-baby images, oversized '
                      'stuffed animals, excessive posing interactions, mass-produced stuffed animal images, AI errors, '
                      'text overlays, watermarks.'),
                     ('Lifestyle',
                      'Nursery cot',
                      'Lifestyle photography: the stuffed animal from the reference image sitting inside a white '
                      'wooden baby cot, surrounded by a cream knitted blanket with waffle texture and two small '
                      'embroidered floral cushions in dusty pink and sage green, soft morning light streaming through '
                      'sheer white curtains creating gentle highlights, cozy Scandinavian nursery aesthetic, shallow '
                      'depth of field with the bear in sharp focus.\n'
                      '\n'
                      'IMPORTANT: Maintain the EXACT appearance of the stuffed animal from the reference image. Keep '
                      'identical fabric texture, color palette, facial features, embroidered details, and proportions. '
                      'Do not modify the animal itself — only create the new scene around it.\n'
                      '\n'
                      'STYLE: Artisan handcrafted product photography, soft natural lighting, editorial quality, '
                      'minimal modern Etsy aesthetic, 1:1 square aspect ratio. AVOID: plush mass-produced look, harsh '
                      'studio lighting, cluttered backgrounds, AI artifacts, text overlays, watermarks.'),
                     ('Gift box',
                      'Gift box',
                      'Product photography: the stuffed animal from the reference image nestled inside an open kraft '
                      'paper gift box lined with cream crinkle tissue paper, a small handwritten gift tag attached '
                      'with natural jute twine (tag blank, no readable text), a single dried eucalyptus sprig placed '
                      'beside the box, flat lay composition on pale linen surface, soft even diffused daylight, '
                      'minimal artisan packaging aesthetic, romantic gift-giving mood.\n'
                      '\n'
                      'IMPORTANT: Maintain the EXACT appearance of the stuffed animal from the reference image. Keep '
                      'identical fabric texture, color palette, facial features, embroidered details, and proportions. '
                      'Do not modify the animal itself — only create the new scene around it.\n'
                      '\n'
                      'STYLE: Artisan handcrafted product photography, soft natural lighting, editorial quality, '
                      'minimal modern Etsy aesthetic, 1:1 square aspect ratio. AVOID: plush mass-produced look, harsh '
                      'studio lighting, cluttered backgrounds, AI artifacts, text overlays, watermarks, any readable '
                      'text on the gift tag.'),
                     ('Cận thêu tay',
                      'Cận thêu tay',
                      'Close-up product photography: detailed close-ups focusing on the hand-embroidery details and '
                      'fabric texture (close-up shots of the hand-embroidery) of the plush toy from the reference '
                      'image, illuminated from the side with soft natural light to highlight each stitch and '
                      'handcrafted texture, extremely shallow depth of field with only the embroidery area in sharp '
                      'focus, showcasing the exquisite craftsmanship worthy of the high price.\n'
                      '\n'
                      'IMPORTANT: Maintain the EXACT shape of the plush toy from the reference image. Preserve the '
                      'fabric texture, color palette, embroidery design, thread color, and stitch style. Do not create '
                      'new embroidery styles or alter existing details—only enlarge what already exists.\n'
                      '\n'
                      'STYLE: Handcrafted product photography, soft natural light, editorial quality, modern '
                      'minimalist Etsy-style aesthetics, 1:1 square aspect ratio. AVOID: mass-produced look, harsh '
                      'studio lighting, cluttered background, AI errors, overlays.The image is blurry and produces '
                      'embroidery details not present in the reference photo.'),
                     ('Lifestyle',
                      'Bé ôm trên chăn muslin',
                      'Lifestyle Photo: A baby lying in a soft, light pink muslin blanket is gently clutching a '
                      'stuffed animal from the reference photo with both hands, creating a cozy and natural nursery '
                      "atmosphere. Only the baby's tummy, chest, and arms are visible, with the stuffed animal "
                      'standing out as the main emotional focal point. Soft natural light from the window, warm '
                      'neutral tones, a minimalist, clean composition with soft materials, and a shallow depth of '
                      'field create a hazy effect, giving the image a light, handcrafted feel – a perfect high-end '
                      'lifestyle photo for Etsy.\n'
                      '\n'
                      'IMPORTANT: Keep the EXACT shape of the stuffed animal from the reference photo. Keep the '
                      'material, color palette, facial features, embroidery details, proportions, and craftsmanship. '
                      'Do not edit the stuffed animal in any way – just create a new background around it. Keep the '
                      'stuffed animal clearly visible and easily recognizable, with the baby naturally holding it '
                      'without obscuring too many details.\n'
                      '\n'
                      'STYLE: Handmade lifestyle product photography, soft natural lighting, editorial quality, modern '
                      'minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                      '\n'
                      'AVOID: Overly harsh studio lighting, cluttered nursery background, unrealistic baby anatomy, '
                      'excessive posing interaction, mass-produced toy images, AI errors, text overlays, watermarks.'),
                     ('Flat lay',
                      'Flat lay baby shower',
                      'The product photo is taken in a flat, top-down composition: the stuffed animal from the '
                      'reference photo is placed in a round wicker basket, covered with a thin layer of voile fabric, '
                      'positioned in the center, surrounded by carefully arranged baby shower decorations — a pair of '
                      'small woolen baby shoes in the upper left, a wooden teething ring with natural beads in the '
                      "upper right, a small cluster of dried baby's breath flowers in the lower left, toys, and a "
                      'neatly folded and gently draped cream-colored muslin baby swaddle in the lower right. Soft '
                      'daylight, an editorial-style composition, and an asymmetrical arrangement create a sense of '
                      'balance and naturalness.\n'
                      '\n'
                      'IMPORTANT: Maintain the EXACT shape of the stuffed animal from the reference photo. Preserve '
                      'the fabric texture, color palette, facial features, embroidery details, and proportions. Do not '
                      'edit the animal itself — only create a new background around it.\n'
                      '\n'
                      'STYLE: Photographic Hand-drawn artwork. Soft, subtle natural lighting, high-quality editing, '
                      'modern minimalist Etsy-style aesthetics, and a 1:1 square aspect ratio. AVOID: Mass-produced '
                      'images, harsh studio lighting, cluttered backgrounds, AI errors, text overlays, and '
                      'watermarks.'),
                     ('Bối cảnh đặc biệt',
                      'Vintage floral',
                      'Lifestyle photography: the stuffed animal from the reference image resting on a vintage floral '
                      'quilted blanket featuring soft pastel rose, dusty pink, and cream floral patterns in '
                      "grandmother's heirloom style, a small antique brass vase with wildflowers (baby's breath, small "
                      'pink roses, lavender sprigs) placed softly beside, warm golden afternoon sunlight filtering in, '
                      'romantic Pinterest-worthy composition, slight film grain aesthetic, nostalgic heritage mood.\n'
                      '\n'
                      'IMPORTANT: Maintain the EXACT appearance of the stuffed animal from the reference image. Keep '
                      'identical fabric texture, color palette, facial features, embroidered details, and proportions. '
                      'Do not modify the animal itself — only create the new scene around it.\n'
                      '\n'
                      'STYLE: Artisan handcrafted product photography, soft natural lighting, editorial quality, '
                      'minimal modern Etsy aesthetic, 1:1 square aspect ratio. AVOID: plush mass-produced look, harsh '
                      'studio lighting, cluttered backgrounds, AI artifacts, text overlays, watermarks.'),
                     ('Editorial/Grid',
                      'Editorial — Grid quy trình',
                      'Create a unified image illustrating the process of making a stuffed animal from the reference '
                      'image, arranged in a high-quality, editorial-style 6-square grid layout (3 columns × 2 rows), '
                      'with thin, soft cream-colored spacing between the squares (no sharp edges, clean grid layout, '
                      'Pinterest style).\n'
                      '\n'
                      '6 SQUARES IN ORDER:\n'
                      '\n'
                      'Square 1 (top left): A flat image of natural cotton linen and textured boucle fabric samples '
                      'neatly arranged on a warm wooden work surface, colors matching the reference bear image, next '
                      'to a wooden embroidery hoop and spools of cream-colored thread.\n'
                      '\n'
                      'Square 2 (top middle): A hand sketching an embroidery pattern (the embroidery part shown in the '
                      'Macro detail image) onto stretched fabric held in a wooden embroidery hoop using white chalk, '
                      'with visible chalk marks.\n'
                      '\n'
                      'Image 3 (top right): A close-up macro shot of a needle pulling the correct colored thread for '
                      'the embroidery pattern on a wooden frame, showing the individual stitches. The shallow depth of '
                      'field highlights the texture of the thread.\n'
                      '\n'
                      "Image 4 (bottom left): Two hands sewing the bear's body pieces together. The soft yellow "
                      'afternoon light clearly highlights the tension of the needle and thread. The cut fabric pieces '
                      'lie next to the sewing machine.\n'
                      '\n'
                      "Image 5 (bottom center): Hands gently stuffing the bear's body with soft cotton (the bear's "
                      'color matches the pattern). The wrinkles in the fabric are being smoothed out, creating a warm '
                      'and intimate close-up.\n'
                      '\n'
                      'Image 6 (bottom right): The finished bear (EXACTLY LIKE the reference image) stands upright '
                      'against a neutral beige linen background. The soft light creates a beautiful image of the '
                      'finished product.\n'
                      '\n'
                      'ENVIRONMENT: A cozy Vietnamese craft workshop, wooden workbenches, warm neutral beige and cream '
                      'tones throughout the images, minimal tools visible (scissors, cream-colored thread spool, '
                      'wooden embroidery hoop), no human faces shown — only hands and tools.\n'
                      '\n'
                      'LIGHTING: Soft, natural side lighting, warm and consistent across all 6 images, cinematic feel, '
                      'the warmth of golden hour.\n'
                      '\n'
                      'IMPORTANT: In image 6, the finished bear MUST be EXACTLY LIKE the reference image — same '
                      'materials, color palette, facial features, embroidery details, and proportions. In the other '
                      'images, the materials and embroidery design must match what will make up the reference bear. No '
                      'changes to the final product design are permitted.\n'
                      '\n'
                      'STYLE: Artistic storytelling, emotionally warm, pleasant, high-end Etsy editorial aesthetics, '
                      'rich fabrics and embroidery, with a particular emphasis on close-up embroidery details.\n'
                      '\n'
                      'AVOID: Overlapping text, logos, watermarks, human faces, edited product designs, cluttered '
                      'backgrounds, harsh studio lighting, AI errors, plastic-looking fabrics, overly saturated '
                      'colors.'))},
 'crown': {'display_name': 'Crown',
           'aliases': ('Crown',
                       'linen crown',
                       'fabric crown',
                       'birthday crown',
                       'baby crown',
                       'child crown',
                       'children crown',
                       'kids crown',
                       'party crown',
                       'embroidered crown',
                       'crown with pom-poms',
                       'pom pom crown',
                       'pompom crown',
                       'vương miện',
                       'vuong mien',
                       'vương miện vải',
                       'vuong mien vai'),
           'lock': 'the main product must remain the same soft fabric birthday crown with the exact pointed crown '
                   'silhouette, upright fabric band, pom-pom or felt-ball tips, linen/fabric texture, embroidery '
                   'placement, thread colors, proportions, scale, and handcrafted birthday accessory identity from '
                   'the source image',
           'shots': (('Product display',
                      'Crown upright on wood birthday table',
                      'The crown stands upright on a wood-grained table. Mini pine cones and a small cake are placed '
                      'around it, with a muted pastel birthday background behind the product. Shoot from a slightly '
                      'horizontal angle with soft clean window sunlight, keeping the scene fresh, bright, and birthday '
                      'themed. Do not add specific characters, names, or new embroidery motifs; keep the embroidery '
                      'versatile for any occasion. 1:1 square aspect ratio. Avoid clutter, harsh studio lighting, '
                      'plastic-looking fabric, flat machine embroidery, AI errors, text overlays, logos, and '
                      'watermarks.'),
                     ('Lifestyle',
                      'Crown on white muslin blanket',
                      'The crown rests slightly off-center on a white muslin blanket with plenty of breathing space. '
                      'Decorate with a teddy bear, fabric book, small pillows, and soft cream or beige nursery tones. '
                      'Use a low frontal view of the crown and natural light through thin curtains for a soft airy '
                      'birthday lifestyle photo. Do not add specific characters, names, or new embroidery motifs. 1:1 '
                      'square aspect ratio. Avoid clutter, harsh lighting, distorted fabric, blurry embroidery, '
                      'text overlays, logos, and watermarks.'),
                     ('Cận thêu tay',
                      'Collage 4 close-ups embroidery and pom-pom',
                      'Create one square composite image made of four small close-up photos. Each small photo focuses '
                      'on close-up details of the crown embroidery, linen fabric texture, pom-pom or felt-ball tips, '
                      'stitches, seams, and handcrafted construction. Keep the details sharp, tactile, and premium. '
                      'Do not redesign the crown or add new embroidery motifs. This is a detail collage only, not a '
                      'multi-output grid. Use clean soft natural white window light. Avoid blurry close-ups, flat '
                      'machine embroidery, text overlays, logos, and watermarks.'),
                     ('Product display',
                      'Five crowns triangular pyramid colorways',
                      'Keep the embroidery intact and show five fabric crowns arranged in a triangular pyramid shape '
                      'on a white wood-grained table beside a window. Use different fabric colors; only if the source '
                      'visibly has an embroidered name may the crowns use different plausible embroidered names while '
                      'keeping the embroidery style and thread colors unchanged. Decorate with a few small '
                      "wildflowers, dried pine cones, and children's wooden toys. Shoot from a low frontal angle in "
                      'clean white window light. Avoid new motifs, character embroidery, clutter, text overlays, '
                      'logos, and watermarks.'),
                     ('Product display',
                      'Crown on high shelf by window',
                      'Place the crown on a high shelf next to a window without changing the embroidery or pattern. '
                      'Turn the embroidered face toward the light so the stitching is clearly visible. Add a simple '
                      'vase of fresh flowers, a few English storybooks, and a baby bracelet as secondary props. Shoot '
                      'from a low horizontal or close 3/4 angle with gentle slanted morning window light and soft '
                      'shadows. Do not add specific embroidery patterns or text. 1:1 square aspect ratio.'),
                     ('Product display',
                      'Three crowns on gray shelf with daffodils',
                      'Show three crowns on a gray wooden shelf by a window, with different fabric colors but the same '
                      'embroidery layout and thread colors. Only if the source visibly has an embroidered name may the '
                      'crowns use different plausible names. Place a vase of yellow daffodils nearby and let clean '
                      'white sunlight stream in from the window. Preserve the crown construction, pom-poms, fabric, '
                      'and stitch quality. Avoid new motifs, clutter, harsh lighting, text overlays, logos, and '
                      'watermarks.'),
                     ('Lifestyle',
                      'Mother hand holding crown',
                      "A mother's hand holds the crown in front of a bright window to show the true size and delicate "
                      'craftsmanship. The person holding the crown wears neutral knit or linen sleeves, and the '
                      'background is softly blurred. The product should look soft, light, and meticulously crafted, '
                      'with embroidery and pom-poms visible. Do not redesign the crown or add motifs. 1:1 square '
                      'aspect ratio. Avoid distorted hands, extra fingers, harsh lighting, clutter, text overlays, '
                      'logos, and watermarks.'),
                     ('Quy trình',
                      'Four-panel crown making process',
                      'Create one square process collage with four small photos: 1) a hand picking white fabric from '
                      'many rolls of multicolored linen; 2) sketching the embroidery design onto a large piece of '
                      'fabric; 3) colorful embroidery being completed on fabric in a round embroidery hoop, one hand '
                      'holding the hoop and the other holding a threaded needle, with embroidery thread and '
                      'multicolored pompoms nearby; 4) sewing the crown shape with a sewing machine. Use soft clean '
                      'window light. The hoop is only a process tool, not the final product. Avoid distorted hands, '
                      'unrealistic needle placement, new motifs, text overlays, logos, and watermarks.'),
                     ('Lifestyle',
                      'Baby wearing crown outdoor birthday',
                      'A baby wearing the crown stands at an outdoor birthday celebration with a happy bright birthday '
                      'tone, holding a piece of cake in hand. Use a full-body shot of the baby while clearly showing '
                      'the embroidery and crown shape. Keep the crown design, fabric color family, pom-poms, and '
                      'stitch texture faithful to the source. Do not add new character embroidery or text. Use soft '
                      'natural daylight, 1:1 square aspect ratio. Avoid distorted baby anatomy, clutter, harsh light, '
                      'text overlays, logos, and watermarks.'),
                     ('Lifestyle',
                      'Baby wearing crown blowing candles',
                      'A baby wearing the crown sits in front of a cake and blows out candles, surrounded by happy '
                      'bright birthday decorations with a small amount of confetti. The embroidery on the crown must '
                      'be clearly visible and sharp. Keep the crown exact in silhouette, fabric, pom-poms, embroidery '
                      'placement, and handmade texture. Do not add new motifs, names, or readable text. Use soft '
                      'natural white window light, 1:1 square aspect ratio. Avoid distorted hands or face, clutter, '
                      'logos, watermarks, and text overlays.'),
                     ('Product display',
                      'Crown on cake stand',
                      'Place the crown on a small cake stand so it sits higher than the tabletop. Put the cake slightly '
                      'behind and off to one side, with cupcakes, pampas grass, and wooden toys as secondary birthday '
                      'props. Shoot from a low frontal angle for an elegant product look. Use window light or '
                      'simulated window studio light that is soft, clear, and neutral. Do not redesign the crown or '
                      'add specific embroidery motifs. 1:1 square aspect ratio. Avoid clutter, harsh lighting, text '
                      'overlays, logos, and watermarks.'))},
 'drawstring_bag': {'display_name': 'Drawstring Bag',
                    'aliases': ('Drawstring Bag',
                                'drawstring bag',
                                'drawstring pouch',
                                'linen drawstring bag',
                                'cotton linen drawstring bag',
                                'embroidered drawstring bag',
                                'embroidered pouch',
                                'linen pouch',
                                'cotton pouch',
                                'jewelry pouch',
                                'gift pouch',
                                'túi rút dây',
                                'tui rut day',
                                'túi dây rút',
                                'tui day rut',
                                'túi rút',
                                'tui rut',
                                'túi vải rút',
                                'tui vai rut'),
                    'lock': 'the main product must remain the same cotton linen drawstring bag/pouch with the exact '
                            'soft rectangular pouch silhouette, gathered drawstring top, cotton rope cords and knots, '
                            'linen weave, fabric color, front embroidery placement, embroidery scale, thread colors, '
                            'natural wrinkles, seams, soft volume, and premium handmade identity from the source image; '
                            'the drawstring cord color must match the source reference',
                    'shots': (('Kitchen product display',
                               'Túi đứng trong giỏ gia vị',
                               'Show one single cotton linen drawstring bag standing naturally in the center of a '
                               'beautiful spice basket on a clean kitchen cooking table. Use refined kitchen decor such '
                               'as small spice jars, wooden spoons, pale wood, linen cloth, and dried herbs. The front '
                               'embroidery must face the camera clearly, with the drawstring top, cotton cords, knots, '
                               'linen texture, soft pouch volume, and natural wrinkles preserved exactly from the '
                               'reference. Use clean bright white daylight and premium Etsy handmade styling.'),
                              ('Jewelry use scene',
                               'Miệng túi mở nhẹ có trang sức',
                               'Place one drawstring bag in the center with the mouth gently opened just enough to show '
                               'a few small jewelry pieces inside, such as a bracelet, ring, or pearl necklace. Use a '
                               'white or cream linen background and a small handmade ceramic tray to suggest function. '
                               'Shoot from a soft 45-60 degree overhead angle with clear white daylight. Keep the same '
                               'bag shape, cord color, gathered top, embroidery position, fabric weave, and thread colors '
                               'from the source image; jewelry is secondary and must not cover the embroidery.'),
                              ('Flat lay',
                               'Túi xẹp tự nhiên trên khăn linen',
                               'Lay one drawstring bag naturally flattened on a light linen cloth in a premium flat lay. '
                               'Let the cotton drawstrings fall softly and visibly. Add tasteful craft props such as '
                               'small scissors, embroidery needle, fabric-covered notebook, dried flowers, and cotton '
                               'cord. The camera must show the fabric texture, hand embroidery relief, seams, and natural '
                               'soft wrinkles clearly. Do not redesign the bag or move the embroidery.'),
                              ('Colorway pair',
                               'Hai túi trên khay trang sức gỗ',
                               'Show two drawstring bags with the same form as the reference, placed side by side on a '
                               'wooden jewelry tray on a dressing table. The two bags may use different linen base colors, '
                               'but the embroidery motif, thread colors, embroidery layout, cord color, drawstring '
                               'construction, seams, and pouch proportions must stay the same as the source. Add refined '
                               'skincare props, flowers, and a clean vanity setting without clutter.'),
                              ('Tabletop storage set',
                               'Ba túi đứng trong khay gỗ sáng',
                               'Show three drawstring bags standing upright together in a shallow light wooden tray on a '
                               'clean bright kitchen or craft table. Do not hang the bags from any hook, rail, peg, wall, '
                               'or drawstring cord. Use soft fabric color variety only for the base fabric while '
                               'preserving the source embroidery, cord color, cord thickness, knots, gathered top, seam '
                               'construction, and pouch proportions. Include folded linen, small dried flowers, wicker '
                               'texture, and soft window light; every bag must rest naturally on the tray or tabletop.'),
                              ('Colorway group',
                               'Bốn túi trên bàn trắng vân gỗ',
                               'Arrange four drawstring bags as a natural group on a white wood-grain table. Each bag may '
                               'have a different fabric color, but all must keep the exact source pouch form, same '
                               'embroidery motif and thread palette, same drawstring cord color, same gathered top, and '
                               'same handmade linen texture. Decorate lightly with a white ceramic vase, linen cloth, '
                               'craft book, and dried branches.'),
                              ('Detail collage',
                               'Bốn ảnh nhỏ cận cảnh thêu',
                               'Create one square detail collage made of four small close-up photos, each showing a '
                               'different macro angle of the embroidery and cotton linen texture on the same drawstring '
                               'bag. The panels must show raised hand stitches, thread direction, tactile thread fibers, '
                               'linen weave, seam or drawstring-channel detail where useful, and natural fabric texture. '
                               'This is a detail-proof collage only; do not create a product colorway grid or redesign '
                               'the embroidery.'),
                              ('Process lifestyle',
                               'Tay thêu trên khung thêu nhỏ',
                               'Show an adult woman sitting at a handmade craft table, carefully embroidering the same '
                               'motif onto a piece of fabric matching the drawstring bag color, using a small embroidery '
                               'hoop, needle with thread, small scissors, thread spools, folded linen, and beautiful '
                               'window light. Hands must be natural and anatomically correct, with a realistic needle '
                               'position. This is a making-process scene; the finished product must still be understood '
                               'as a cotton linen drawstring bag, not a hoop product.'),
                              ('Basket lifestyle',
                               'Túi trong giỏ mây nhỏ',
                               'Place one drawstring bag in a small wicker basket on a light wood table. Use refined '
                               'decor such as linen cloth, small ceramic vase, white candle, dried flowers, and a '
                               'fabric-covered book. The front embroidery must be visible and sharp, with clean white '
                               'daylight and a soft premium handmade mood. Preserve the source bag shape, cords, fabric, '
                               'embroidery scale, and natural wrinkles.'),
                              ('Family lifestyle',
                               'Em bé đưa túi cho mẹ',
                               'Create a bright living-room lifestyle photo where a baby or young child hands the '
                               'drawstring bag to the mother, with small items inside so the pouch has gentle natural '
                               'volume. Keep the scene safe, clean, airy, and premium. Faces can be cropped or secondary. '
                               'The bag must remain the focal product, with its front embroidery visible and not covered '
                               'by hands; preserve cord color, gathered top, pouch form, and stitch texture.'),
                              ('Use detail',
                               'Tay phụ nữ bỏ đồ nhỏ vào túi',
                               'Show an adult woman hand placing small items into the drawstring bag. Use airy premium '
                               'light, soft neutral tabletop styling, and focus on the bag opening, cords, and embroidery. '
                               'The bag may look slightly fuller from the contents, but the source shape, fabric weave, '
                               'drawstring color, embroidery placement, and thread details must not change. Hands must '
                               'be natural with no extra fingers.'),
                              ('Gift presentation',
                               'Túi xẹp nhẹ trong hộp quà mở',
                               'Place one drawstring bag neatly inside a small open paper gift box. The bag should be '
                               'slightly flattened or gently folded, not overly inflated, with the embroidered front '
                               'facing upward and clearly visible. Use a small minimal light-colored box and very light '
                               'decor such as linen cloth or pale paper background. Do not place anything on top of the '
                               'bag or cover the embroidery; preserve the source fabric, cords, stitches, and handmade '
                               'identity.'))},
 'fabric_cross': {'display_name': 'Fabric Cross',
                  'aliases': ('Fabric Cross',
                              'fabric cross',
                              'soft cross',
                              'linen cross',
                              'baby cross',
                              'cross keepsake',
                              'thánh giá vải',
                              'thanh gia vai'),
                  'lock': 'the main product must remain the same soft fabric cross keepsake with the exact cross '
                          'shape, stitched edge, fabric texture, embroidery/name placement, scale, and gentle baby '
                          'keepsake identity from the source image',
                  'shots': (('Lifestyle',
                             'Baby cầm 2 tay',
                             'Life photography: A baby gently cradles the fabric cross from the reference image with '
                             'both hands, while relaxing in a cozy, neutral-toned nursery or soft home space. The warm '
                             'and natural interaction makes the fabric cross the primary emotional focal point. Soft '
                             'natural light from the window, warm cream and beige tones, a clean, minimalist '
                             'background with soft blankets, knitwear, and subtle details of the nursery create a '
                             'slightly blurred effect. The shallow depth of field gives a gentle, ethereal feel, '
                             'evoking a sense of delicate handcrafted keepsake—a high-end life photography perfect for '
                             'Etsy.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. Keep '
                             'the shape, size, proportions, fabric material, embroidery design, thread color, '
                             'stitching details, loop placement, and craftsmanship characteristics. Do not modify the '
                             'fabric cross in any way—only create a new context around it. Keep the fabric cross '
                             'clearly visible and easily recognizable, with the baby holding it naturally without '
                             'obscuring too much detail.\n'
                             '\n'
                             'STYLE: Handmade lifestyle product photography, soft natural lighting, editorial quality, '
                             'modern minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: overly harsh studio lighting, cluttered background, unrealistic baby anatomy, '
                             'excessive posing interaction, mass-produced images, AI errors, text overlays, '
                             'watermarks.'),
                            ('Product display',
                             'Tựa gấu teddy + chăn len',
                             'The fabric cross, taken from a reference image, is positioned upright and gently resting '
                             'against a soft teddy bear in a cozy nursery setting, on a cream-colored wool blanket '
                             'with a few dried flowers or delicate botanical details scattered naturally around. Warm '
                             'natural light diffuses from the window, the gentle beige and ivory tones, the slightly '
                             'muted minimalist background, the central composition with the fabric cross as the clear '
                             'focal point, and the shallow depth of field create a soft, hazy effect, giving it a '
                             'delicate, handcrafted keepsake feel—a high-end product photo for Etsy.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. Keep '
                             'the shape, size, proportions, fabric material, embroidery design, thread color, '
                             'stitching details, loop placement, any personalized text, and handcrafted '
                             'characteristics. Do not modify the fabric cross in any way—only create a new setting '
                             'around it. The teddy bear and surrounding props should support the composition without '
                             'obscuring the fabric cross too much.\n'
                             '\n'
                             'STYLE: Handmade product photography, soft natural lighting, editorial quality, modern '
                             'minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: overly harsh studio lighting, cluttered background, retouched embroidery, '
                             'mass-produced look, unrealistic textures, AI errors, text overlays, watermarks.'),
                            ('Product display',
                             'Treo mobile cũi gỗ',
                             'Product photo of the fabric cross, taken from a reference image, hanging on a natural '
                             'wood crib mobile in a bright, cozy nursery, displayed above a soft, neutral-colored crib '
                             'with cream-colored bedding and a light pastel duvet. The minimalist, clean layout '
                             'features the fabric cross as the main focal point, soft natural light from the side '
                             'window, warm ivory and beige tones, a slightly blurred nursery background, a few dried '
                             'grasses or soft natural decorations nearby, and a shallow depth of field creating a '
                             'soft, ethereal effect, giving the image a gentle, handcrafted keepsake feel – a high-end '
                             'product photo for Etsy.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. Keep '
                             'the shape, size, proportions, fabric material, embroidery design, thread color, '
                             'stitching details, hanging loop placement, any personalized text, and handcrafted '
                             'characteristics intact. Do not modify the fabric cross in any way—only create a new '
                             'context around it. Crib mobiles and other elements in the nursery should support the '
                             'layout without obscuring or distracting attention from the fabric cross.\n'
                             '\n'
                             'STYLE: Handmade product photography, soft natural lighting, editorial photo quality, '
                             'modern minimalist Etsy-style aesthetic, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: Harsh studio lighting, cluttered nursery backgrounds, edited embroidery, '
                             'unrealistic crib proportions, mass-produced look, AI errors, text overlays, watermarks.'),
                            ('Product display',
                             'Trên tay nắm cửa gỗ',
                             'This product photo of a fabric cross, taken from a reference image, hangs neatly on a '
                             "round wooden doorknob in a bright, quiet children's room or a lightly decorated home "
                             'interior. The fabric cross is displayed naturally against a light oak door frame, with a '
                             "minimalist children's room backdrop that is subtly blurred, such as a white wardrobe, "
                             'neutral-colored wall art, or sheer curtains in the distance. The soft natural light from '
                             'the window, the warm ivory, beige, and light wood tones, the neat composition with the '
                             'fabric cross as the clear focal point, and the shallow depth of field create a gentle, '
                             'hazy effect, giving it a delicate, handcrafted feel—a high-end product photo for Etsy. \n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. Keep '
                             'the shape, size, proportions, fabric material, embroidery design, thread color, '
                             'stitching details, hanging loop placement, any personalized text, and handcrafted '
                             'characteristics intact. Do not modify the fabric cross itself in any way — just create a '
                             'new background around it. This guide applies to any fabric cross design, so keep the '
                             'embroidery, colors, and personalization as they are in the reference image. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, soft natural lighting, editorial image quality, '
                             'modern minimalist Etsy-style aesthetic, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: Harsh studio lighting, cluttered background, edited embroidery, unrealistic door '
                             'or room proportions, mass-produced look, AI errors, text overlays, watermarks.'),
                            ('Product display',
                             '2 cross trên chăn dệt',
                             'The product image displays two fabric crosses from the reference photo, elegantly '
                             'arranged on a richly textured knitted blanket, topped with a soft linen overlay, '
                             'surrounded by a small bundle of dried eucalyptus leaves and scattered eucalyptus '
                             'branches arranged naturally. The two fabric crosses are placed side-by-side in a '
                             'balanced composition, gently illuminated by warm sunlight to create a tranquil, '
                             'handcrafted atmosphere. The image is clean, cozy, artistic with a shallow depth of field '
                             'and soft, natural shadows – a high-quality product photo on Etsy. \n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of both fabric crosses from the reference photo. '
                             'Preserve the shape, size, proportions, fabric texture, embroidery style, thread color, '
                             'stitching details, ribbon placement, and handcrafted characteristics. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, soft natural lighting, edited image quality, '
                             'modern minimalist aesthetic in the Etsy style, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: Harsh studio lighting, cluttered backgrounds, embroidery editing, unrealistic '
                             'materials, mass-produced look, AI errors, text overlays, watermarks.'),
                            ('Lifestyle',
                             'Candid bé cầm 1 tay',
                             'A candid photo of a baby holding a fabric cross from the reference image in one hand, '
                             'while gently holding a bouquet of flowers in the other. The baby is wearing a simple, '
                             'light-colored dress and standing in a church. The fabric cross is clearly visible, with '
                             'its prominent hand-embroidered details. Soft natural light from the window creates a '
                             'quiet, warm atmosphere, with a shallow depth of field that subtly blurs the background, '
                             "emphasizing the fabric cross as the main focal point. The baby's face is not visible, "
                             'and the composition conveys a gentle, sentimental mood of a handcrafted gift, perfect '
                             'for a high-quality photo on Etsy.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. Keep '
                             'the shape, size, proportions, fabric material, embroidery style, thread color, stitching '
                             'details, hook placement, any personalized text, and handcrafted characteristics. Do not '
                             'modify the fabric cross itself in any way—only create a new setting around it. The baby '
                             'should interact naturally with the fabric cross, without obscuring any of its details.\n'
                             '\n'
                             'STYLE: Lifestyle-inspired handcrafted product photography, soft natural lighting, '
                             'editorial quality, modern minimalist Etsy-style aesthetic, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: Harsh studio lighting, cluttered backgrounds, unrealistic baby anatomy, excessive '
                             'posing, mass-produced stuffed toy appearance, AI errors, text overlays, watermarks.'),
                            ('Quy trình',
                             'Quy trình — 4 ảnh nhỏ',
                             'This set of four small photos documents the process of creating a fabric cross:\n'
                             '\n'
                             'The first image shows a pencil sketch of the cross on linen fabric the same color as the '
                             'sample cross, with the pattern and embroidery clearly visible in the background.\n'
                             '\n'
                             'The second image shows the embroidery thread being threaded through the needle, '
                             'preparing for embroidery.\n'
                             '\n'
                             'The third image shows the embroidery process on an embroidery frame, with the details of '
                             'the meticulous embroidery design clearly visible.\n'
                             '\n'
                             'The fourth image shows the finished fabric cross hanging on a soft ribbon, with the '
                             'perfect embroidery and the finished product prominently displayed, gently placed on a '
                             'soft surface with dried reeds and a clean backdrop.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross as in the reference images. '
                             'Preserve the shape, size, proportions, fabric material, embroidery pattern, thread '
                             'color, embroidery details, loop placement, and any personalized text. What are the '
                             'details and craftsmanship? Do not modify the fabric cross itself in any way—only '
                             'describe the creation process and the new context surrounding it.\n'
                             '\n'
                             'STYLE: Handcrafted product photography, soft natural lighting, editorial image quality, '
                             'modern minimalist Etsy style. Beautiful images, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: Incorrect embroidery placement, overly forced hand posture, blurry embroidery, '
                             'disproportionate proportions, overly cluttered background, AI errors, text overlapping '
                             'the image, blurry images.'),
                            ('Product display',
                             'Product — Khung cảnh nursery',
                             'This product photo of a fabric cross, based on a reference image, is shown standing '
                             'upright on a rustic wooden table with several classic wooden letter blocks surrounding '
                             'it. The fabric cross stands out as the main focal point, with its embroidered motif. '
                             'Nearby, a small potted succulent, some natural wool yarn, and a soft woven basket can be '
                             'seen in the background, creating a cozy and rustic atmosphere. Warm, gentle natural '
                             'sunlight shines from the side, creating soft shadows and highlighting the handcrafted '
                             'texture of the fabric cross. The minimalist composition and shallow depth of field '
                             'create a subtle blurring effect in the background, making it a high-quality product '
                             'photo for Etsy.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. Keep '
                             'the shape, size, proportions, fabric texture, embroidery design, thread color, stitching '
                             'details, hook placement, any personalized text, and handcrafted characteristics intact. '
                             'Do not modify the fabric cross itself in any way—only create a new context around it. '
                             'The surrounding items should highlight the natural beauty and handcrafted quality of the '
                             'cross without obscuring or distracting from it.\n'
                             '\n'
                             'STYLE: Handcrafted product photography, soft natural lighting, editorial quality, modern '
                             'minimalist Etsy-style aesthetic, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: Harsh studio lighting, cluttered backgrounds, heavily edited embroidery, '
                             'mass-produced look, unrealistic textures, AI errors, text overlays, watermarks.'),
                            ('Cận thêu tay',
                             'Cận thêu tay',
                             'Take a close-up photograph of the fabric cross from the reference image, focusing on the '
                             'exquisite hand-embroidered details, with clearly defined threads and beautiful '
                             'stitching. The fabric cross should be the main focal point, highlighting the embroidery '
                             'and stitching. Soft, natural light from the side will emphasize the depth of the '
                             'embroidery, with a shallow depth of field to create a hazy effect around the fabric. The '
                             'fabric should be neutral and clean, and the handcrafted details must be clearly visible, '
                             'emphasizing the quality of the product.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. '
                             'Preserve the fabric, embroidery details, thread color, stitching, proportions, and '
                             'handcrafted characteristics. Do not alter the cross in any way—only enlarge the existing '
                             'embroidery details.\n'
                             '\n'
                             'STYLE: Close-up photos of handcrafted products, soft natural lighting, high-quality '
                             'editing, modern minimalist Etsy-style aesthetics, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: blurry seams, images that look like they were created by machines, edited '
                             'embroidery patterns, harsh lighting, overexposed highlights, AI errors, text overlaid on '
                             'images, watermarks.'),
                            ('Lifestyle',
                             'Candid bé + cross #2',
                             'A candid photograph of a fabric cross from a reference image, gently cradled in the '
                             'hands of an adult beside a sleeping baby in a cozy, softly lit nursery. The exquisitely '
                             "embroidered fabric cross stands out in the adult's hands, its delicate stitching "
                             'highlighting the intricate details. The soft crib and bedding in the background are '
                             'subtly blurred, creating a tranquil and peaceful atmosphere. Gentle natural light from '
                             'the window illuminates the fabric cross, creating a warm, tender mood perfect for a '
                             'handcrafted commemorative photograph.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. Keep '
                             'the shape, size, proportions, fabric material, embroidery style, thread color, stitching '
                             'details, placement of the loops, any personalized text, and handcrafted characteristics. '
                             'Do not modify the fabric cross itself in any way—only create a new setting around it. '
                             'The fabric cross should be the main focal point with the baby sleeping peacefully in the '
                             'background.\n'
                             '\n'
                             'STYLE: Lifestyle-inspired handcrafted product photography, soft natural lighting, edited '
                             'image quality, modern minimalist Etsy-style aesthetics, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: Harsh studio lighting, cluttered backgrounds, heavily edited embroidery, '
                             'unrealistic baby anatomy images, mass-produced appearance, AI errors, text overlapping '
                             'images, blurry images.'),
                            ('Product display',
                             'Product display đơn',
                             'Product photo of the fabric cross, taken from a reference image, is gently draped over '
                             'the handle of a stroller in a sun-drenched park setting. The delicately embroidered '
                             'fabric cross stands out against the neutral-colored stroller fabric and the soft blanket '
                             'inside. The backdrop is filled with natural greenery and soft daylight, creating a '
                             'peaceful and tranquil outdoor atmosphere. The composition focuses on the fabric cross as '
                             'the main focal point, with a shallow depth of field creating a subtle blur in the '
                             'background, highlighting the handcrafted details. The soft ribbon adds a delicate charm '
                             'to the overall design, ideal for a high-end Etsy product.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric cross from the reference image. Keep '
                             'the shape, size, proportions, fabric material, embroidery style, thread color, stitching '
                             'details, ribbon placement, any personalized text, and handcrafted features. Do not '
                             'modify the fabric cross itself in any way—only create a new context around it. The cart '
                             'and surrounding items should complement the cross without overshadowing it.\n'
                             '\n'
                             'STYLE: Handcrafted product photography, soft natural lighting, editorial quality, modern '
                             'minimalist Etsy-style aesthetic, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: Harsh studio lighting, cluttered backgrounds, heavily edited embroidery, '
                             'unrealistic cart proportions, mass-produced look, AI errors, text overlays, watermarks.'),
                            ('Product display',
                             'Composite layout',
                             'The product image shows a fabric cross inspired by a reference image. Three fabric '
                             'crosses in three different colors (three different colors but the same embroidery style '
                             'and thread color) are prominently displayed inside a wicker basket. The basket is placed '
                             'on a table, further decorated with a few flower petals, such as pastel wildflowers, '
                             'along with soft green plants and moss, creating a rustic, natural look. The arrangement '
                             'is set outdoors, with gentle sunlight shining through, creating a warm and pleasant '
                             'atmosphere. The fabric crosses should be the main focal point, with the natural beauty '
                             'of the flowers and soft ribbons adding elegance.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric crosses from the reference image. '
                             'Preserve the shape, size, proportions, fabric material, embroidery style, thread color, '
                             'stitching details, ribbon placement, any personal lettering, and handcrafted features. '
                             'Do not modify the fabric cross itself in any way—simply create a new composition around '
                             'it. The basket should contain fresh spring flowers to highlight the natural beauty '
                             'without overshadowing the fabric cross.\n'
                             '\n'
                             'STYLE: Handmade product photography, soft natural lighting, editorial quality, modern '
                             'minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: Harsh studio lighting, cluttered backgrounds, over-edited embroidery, unrealistic '
                             'materials, mass-produced look, AI errors, text overlays, watermarks.'),
                            ('Editorial/Grid',
                             'Editorial — Grid layout',
                             'Product photos of handcrafted fabric crosses are taken from a reference image. A fabric '
                             'cross is displayed hanging on a wooden hook in a quiet and elegant interior space. '
                             'Beside it, a ceramic vase filled with fresh flowers sits on a wooden surface covered '
                             'with soft, neutral-colored linen, creating a warm and peaceful atmosphere. Gentle '
                             'natural light shines in from the left, illuminating the scene with a delicate and airy '
                             'feel. The fabric cross is the central focal point of the photo, while the surrounding '
                             'decorations add balance and tell a subtle story. The clean, minimalist, and lightly '
                             'styled background contributes to a refined editorial look. A standout product photo on '
                             'Etsy.\n'
                             '\n'
                             'IMPORTANT: The EXACT shape of the fabric cross is retained from the reference image. The '
                             'fabric texture, color palette, embroidery style, proportions, hanging ribbon details, '
                             'and overall handcrafted appearance are also preserved. Do not edit the fabric cross '
                             'itself – only recreate the surrounding background and the life scene around it.\n'
                             '\n'
                             'STYLE: Handmade product photography, soft natural lighting, editorial quality, modern '
                             'minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                             '\n'
                             'AVOID: altering the cross design on the fabric, changing the embroidery, creating a '
                             'mass-produced look, overly harsh studio lighting, cluttered background, distracting '
                             'props, AI errors, text overlays, watermarks.'))},
 'bride_handkerchief': {'display_name': 'Bride Handkerchief',
                        'aliases': ('Bride Handkerchief',
                                    'bride handkerchief',
                                    'bridal handkerchief',
                                    'wedding handkerchief',
                                    'embroidered handkerchief',
                                    'khăn tay cô dâu',
                                    'khan tay co dau'),
                        'lock': 'the main product must remain the same embroidered wedding handkerchief or soft cloth '
                                'square with the exact fabric, edge finish, fold/open shape, motif placement, stitch '
                                'colors, and elegant keepsake scale from the source image',
                        'shots': (('Lifestyle',
                                   '2 khăn 2 màu cạnh nhau',
                                   'A lifestyle-style photograph of two hand-embroidered wedding handkerchiefs, taken '
                                   'from a reference image, shows two handkerchiefs in two different colors (with the '
                                   'same embroidery style) gently cradled in two hands, bathed in soft natural light. '
                                   'The handkerchiefs are elegantly displayed with their exquisite embroidery. Behind '
                                   "them is the bride's bridal room, with her wedding dress and suit hanging. The "
                                   'background is suddenly blurred, focusing attention on the handkerchiefs, while the '
                                   'overall scene conveys warmth, elegance, and timeless beauty.\n'
                                   'IMPORTANT: Maintain the EXACT shape of the handkerchiefs from the reference image. '
                                   'Preserve the fabric texture, embroidery details, proportions, and overall '
                                   'aesthetic. Do not alter the handkerchiefs in any way—simply create a new setting '
                                   'around them. The handkerchiefs should be the main focal point, with surrounding '
                                   'props highlighting their beauty.\n'
                                   'STYLE: Handcrafted product photography, soft natural light. Lightweight, '
                                   'high-quality editing, modern minimalist aesthetic. Etsy style, 1:1 square aspect '
                                   'ratio.\n'
                                   '\n'
                                   'AVOID: Overly harsh studio lighting, cluttered composition, altered backgrounds '
                                   'and embroidery patterns, unrealistic textures, mass-produced images, AI errors, '
                                   'text overlays, watermarks.'),
                                  ('Product display',
                                   'Flat display đơn',
                                   'This product image of a handmade wedding handkerchief is taken from a reference '
                                   'photo. The image shows a baby handing the handkerchief to the bride (only the '
                                   "bride's hand and the baby handing the handkerchief are visible) during a simple "
                                   'wedding ceremony. The handkerchief is the focal point of the photo, clearly '
                                   'showing the embroidery. The soft, natural light of the outdoor setting creates a '
                                   'stunning product photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the wedding handkerchief is retained from the '
                                   'reference photo. The fabric texture, color palette, embroidery style, proportions, '
                                   'edging details, and overall handcrafted look are preserved. The handkerchief '
                                   'itself has not been edited – only the surrounding background and the lifelike '
                                   'setting have been recreated. \n'
                                   '\n'
                                   'STYLE: Handmade product photography, romantic wedding style, soft natural light, '
                                   "high-quality editing, Etsy's modern minimalist aesthetic, 1:1 square aspect "
                                   'ratio. \n'
                                   '\n'
                                   'AVOID: editing the handkerchief design, changing the embroidery pattern, creating '
                                   'a mass-produced look, overly harsh studio lighting, cluttered backgrounds, '
                                   'distracting props, AI errors, text overlays, and watermarks.'),
                                  ('Gift box',
                                   'Gift box',
                                   'This product image shows a hand-embroidered wedding handkerchief, neatly placed in '
                                   'an elegant gift box lined with ivory silk paper. The handkerchief is perfectly '
                                   'folded to highlight the delicate beauty of the embroidery. The box is gently '
                                   'opened, revealing the handkerchief, and soft natural light accentuates the subtle '
                                   'details of the fabric and embroidery. Placed on a white table, surrounded by two '
                                   'wedding rings and a large bridal bouquet, it adds a romantic touch to the scene. '
                                   'The minimalist, clean background emphasizes the elegance, making it a perfect '
                                   'commemorative gift for the bride.\n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape of the handkerchief as in the reference image. '
                                   'Keep the fabric, embroidery details, thread color, proportions, and overall '
                                   'aesthetic unchanged. Do not alter the handkerchief in any way—simply create a new '
                                   'setting around it. The gift box should highlight the beauty of the handkerchief '
                                   'without overshadowing it. STYLE: Handcrafted product photography, soft natural '
                                   'lighting, edited image quality, modern minimalist Etsy-style aesthetics, 1:1 '
                                   'square aspect ratio.\n'
                                   '\n'
                                   'AVOID: Overly elaborate packaging, harsh studio lighting, excessively retouched '
                                   'embroidery, cluttered composition, mass-produced appearance, AI errors, text '
                                   'overlays, watermarks.'),
                                  ('Product display',
                                   '3 khăn 3 màu',
                                   'The product image shows three hand-embroidered wedding handkerchiefs (different '
                                   'colors but the same embroidery style), elegantly arranged on a natural wood tray, '
                                   'with soft pastel colors and delicate floral patterns. The handkerchiefs are neatly '
                                   'folded, the embroidery clearly visible. A large bouquet of fresh wedding flowers, '
                                   'matching the embroidery on the handkerchiefs, and two wedding rings are gently '
                                   'arranged beside them, highlighting a tender, romantic feel. The scene is softly '
                                   'illuminated by warm natural light, creating a refined and intimate atmosphere. The '
                                   'soft material and exquisite embroidery are highlighted, making it a perfect '
                                   'keepsake for special occasions.\n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape of the handkerchiefs as shown in the reference '
                                   'image. Keep the fabric, embroidery details, proportions, and overall aesthetic '
                                   'unchanged. Do not alter the handkerchiefs in any way—simply create a new layout '
                                   'around them. The handkerchief should be the main focal point, with surrounding '
                                   'items highlighting its beauty.\n'
                                   '\n'
                                   'STYLE: Handmade product photography, soft natural lighting, edited image quality, '
                                   'modern minimalist aesthetic in the Etsy style, 1:1 square aspect ratio.\n'
                                   '\n'
                                   'AVOID: Harsh studio lighting, cluttered backgrounds, over-edited embroidery, '
                                   'unrealistic textures, mass-produced look, AI errors, text overlays, watermarks.'),
                                  ('Product display',
                                   'Trên vải mềm + decor',
                                   'This photo shows an embroidered wedding handkerchief, taken from a reference '
                                   'image, placed on a soft white veil, surrounded by wedding invitations, two rings, '
                                   'and a large wedding bouquet. The handkerchief is positioned in the center of the '
                                   'photo to highlight the delicate embroidery. Soft natural light from a nearby '
                                   'window accentuates the fabric and embroidery, creating a romantic and elegant '
                                   'atmosphere for this wedding gift.\n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape of the handkerchief from the reference image. '
                                   'Keep the fabric, embroidery details, and personalized text unchanged. Do not alter '
                                   'the handkerchief in any way—only create a new setting around it.\n'
                                   '\n'
                                   'STYLE: Handmade product photography, soft natural light, high-quality editing, '
                                   'modern minimalist Etsy-style aesthetic, 1:1 square aspect ratio.\n'
                                   '\n'
                                   'AVOID: cluttered layouts, harsh lighting, altered embroidery patterns, fake '
                                   'materials, AI errors, text overlays, and watermarks.'),
                                  ('Lifestyle',
                                   'Chú rể cầm khăn',
                                   'This lifestyle-style photo shows the groom holding a hand-embroidered handkerchief '
                                   "from the reference image, gently placed in the bride's hand. The handkerchief, "
                                   "with its exquisite embroidery is clearly visible, and the groom's hands are subtly "
                                   'positioned to highlight the delicate details. Soft natural light illuminates the '
                                   'handkerchief and the meticulous embroidery, creating a warm and tender moment. The '
                                   'background is a light, neutral-toned interior space with a cozy, minimalist '
                                   'atmosphere, highlighting the handcrafted quality of the handkerchief.\n'
                                   'IMPORTANT: Maintain the EXACT shape of the handkerchief from the reference image. '
                                   'Keep the fabric, embroidery details, proportions, and overall aesthetic unchanged. '
                                   'Do not alter the handkerchief in any way—simply create a new context around it. '
                                   "The bride's hands should interact naturally with the handkerchief, and the context "
                                   'should maintain a soft and focused feel.\n'
                                   'STYLE: Photograph handcrafted products in a lifestyle style, with soft, natural '
                                   'lighting, high-quality editing, a modern minimalist Etsy aesthetic, and a 1:1 '
                                   'square aspect ratio.\n'
                                   'AVOID: overly harsh studio lighting, cluttered backgrounds, digitally altered '
                                   'embroidery, unrealistic hand poses, overly stylized interactions, AI errors, text '
                                   'overlays, and watermarks.'),
                                  ('Product display',
                                   'Tổng hợp nhiều góc',
                                   'This product photo set includes four close-up shots of the embroidery on the '
                                   'handkerchief to highlight the delicate details of the hand-embroidered wedding '
                                   'handkerchief.\n'
                                   '\n'
                                   'All photos should be taken with soft, natural light to create depth, and with a '
                                   'blurred background to focus on the embroidery details and fabric texture.\n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape of the handkerchief in the reference photos. '
                                   'Keep the fabric material, embroidery style, thread color, stitching style, and '
                                   'proportions unchanged. Do not edit the handkerchief in any way—simply create a new '
                                   'context around it.\n'
                                   '\n'
                                   'STYLE: Handmade product photography, soft natural light, editorial quality, modern '
                                   'minimalist Etsy-style aesthetic, 1:1 square aspect ratio.\n'
                                   '\n'
                                   'AVOID: Blurry stitching, a machine-like appearance, altered embroidery style, '
                                   'harsh lighting, overexposed highlights, AI errors, text overlays, watermarks.'),
                                  ('Product display',
                                   'Flat display #3',
                                   "This lifestyle photograph captures a close-up of a woman's hands carefully "
                                   'embroidering a scarf pattern on a circular embroidery hoop. The image focuses on '
                                   'the delicate, precise embroidery process, showing the thread being pulled through '
                                   'the fabric. The hands are depicted in a natural, relaxed posture, highlighting the '
                                   'skill and meticulousness. The surrounding space is decorated in a minimalist and '
                                   'handcrafted style, including neutral-colored embroidery thread, a small pair of '
                                   'scissors, and a few dried flowers. Soft natural light from the side accentuates '
                                   'the texture of the fabric and thread, creating a warm, artistic atmosphere.\n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape of the embroidery pattern from the reference '
                                   'photograph. Keep the fabric texture, embroidery pattern, thread color, needle '
                                   'placement, and proportions unchanged. Do not modify the embroidery pattern or '
                                   'stitch details—simply create a new context around it.\n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, soft natural lighting, high-quality '
                                   'editing, modern minimalist aesthetics in the Etsy style, 1:1 square aspect ratio.\n'
                                   '\n'
                                   'AVOID: Incorrect needle placement, unthreaded needles, blurry stitching, overly '
                                   'stylized hands, cluttered backgrounds, AI errors, text overlapping images, blurry '
                                   'images.'))},
 'vows_book': {'display_name': 'Vows Book',
               'aliases': ('Vows Book',
                           'vow book',
                           'vows book',
                           'wedding vows',
                           'bride vows',
                           'groom vows',
                           'sổ vows',
                           'so vows'),
               'lock': 'the main product must remain the same fabric-covered vow book/booklet with the exact book '
                       'cover shape, spine/edge construction, embroidered cover layout, lettering placement, fabric '
                       'texture, and wedding keepsake identity from the source image',
               'shots': (('Lifestyle',
                          'Đôi uyên ương cùng đọc',
                          'This product image of a handmade wedding vow book is taken from a reference photo. The '
                          'bride and groom are photographed from behind in an outdoor wedding setting, each holding a '
                          'vow book pointing towards the sky. The couple stands under a clear blue sky with soft '
                          'natural sunlight, creating a romantic and elegant atmosphere. The vow books are the main '
                          "focus of the photo, while the couple's wedding attire and the greenery in the distance "
                          'below add context and emotion. The background is clean, airy, and slightly blurred, with '
                          'ample open space and a soft depth of field, creating a sophisticated, almost edited look. A '
                          'standout product photo on Etsy.\n'
                          '\n'
                          'IMPORTANT: The EXACT shape of the vow books from the reference photo is preserved. The '
                          'linen texture, color palette, embroidery style, cover layout, proportions, and overall '
                          'handmade appearance are also retained. The vow books themselves are not edited – only the '
                          'surrounding background and the life-like setting are recreated.\n'
                          '\n'
                          'IMPORTANT: The exact shape of the vow books is preserved from the reference photo. The '
                          'linen texture, color palette, embroidery style, cover layout, proportions, and overall '
                          'handmade look are retained. No editing of the vow books themselves is done – only the '
                          'surrounding background and the life-like setting is reproduced.\n'
                          '\n'
                          'STYLE: Handmade product photography, romantic wedding lifestyle, soft natural lighting, '
                          'editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                          '\n'
                          'AVOID: altering vow book design, changing embroidery, mass production style, harsh studio '
                          'lighting, cluttered background, distracting props, AI errors, text overlays, watermarks.'),
                         ('Product display',
                          '2 cuốn windowsill (active)',
                          'This product photo of a handmade wedding vow book is taken from a reference image. Two vow '
                          'books are displayed upright on a clean white table in an elegant interior space. A white '
                          'ceramic vase filled with fresh flowers sits between the two books, while several delicate '
                          'wedding-themed decorative items such as candlesticks, rings, and a small camera are '
                          'arranged around them. Soft natural light creates a romantic and intimate atmosphere. The '
                          'two vow books are the main focus of the photo, with the surrounding items adding balance '
                          'and telling the story. The clean, minimalist, and slightly blurred background, with plenty '
                          'of empty space and a soft depth of field, creates a professional, editorial look. A '
                          'standout product photo on Etsy.\n'
                          '\n'
                          'IMPORTANT: The EXACT shape of the vow books from the reference image is preserved. The '
                          'linen texture, color palette, embroidery style, cover layout, proportions, and overall '
                          'handcrafted look are also retained. Do not edit the vow books themselves – only recreate '
                          'the background and surrounding scenery.\n'
                          '\n'
                          'STYLE: Handcrafted product photography, romantic wedding table decorations, soft natural '
                          'lighting, professional image quality, modern minimalist Etsy aesthetic, 1:1 square aspect '
                          'ratio.\n'
                          '\n'
                          'AVOID: altering the vow book design, changing embroidery patterns, mass production style, '
                          'harsh studio lighting, cluttered backgrounds, distracting props, AI errors, text overlays, '
                          'watermarks.'),
                         ('Flat lay',
                          'Flat lay — vow books + props',
                          'This product image of a handmade wedding vow book is taken from a reference photo. Two vow '
                          'books are displayed upright on a small wooden stand on a pristine white table in an elegant '
                          'outdoor wedding setting. Surrounding the books are romantic wedding-themed details such as '
                          'white bouquets, soft greenery, a wooden Welcome sign, and a few small photos, creating a '
                          'beautifully decorated wedding scene. Warm natural sunlight gently illuminates the scene, '
                          'creating a romantic and timeless atmosphere. The vow books are the central focus of the '
                          'photo, while the surrounding decorations add balance and tell a story. The backdrop is an '
                          'outdoor garden with soft greenery and a natural bokeh effect, subtly blurred to focus '
                          'attention on the books. A standout product photo on Etsy.\n'
                          '\n'
                          'IMPORTANT: The EXACT shape of the vow books from the reference photo is preserved. Maintain '
                          'the original linen texture, color palette, embroidery style, cover layout, proportions, and '
                          'overall handcrafted look. Do not edit the vow books themselves – only recreate the '
                          'background and surrounding scenery.\n'
                          '\n'
                          'STYLE: Handcrafted product photography, romantic wedding table setting, soft natural '
                          "lighting, professional image quality, Etsy's modern minimalist aesthetic, 1:1 square aspect "
                          'ratio.\n'
                          '\n'
                          'AVOID: altering the vow book design, changing the embroidery patterns, mass production '
                          'style, harsh studio lighting, cluttered backgrounds, distracting props, AI errors, text '
                          'overlays, watermarks.'),
                         ('Cận thêu tay',
                          'Cận thêu tay',
                          'This product image of the handmade wedding vow book is taken from a reference photo. The '
                          'bride and groom stand side-by-side in a stunning outdoor wedding setting in a garden, '
                          'smiling at the camera while each holds the vow book aloft above their heads. The couple are '
                          'dressed in elegant wedding attire, creating a joyful and romantic atmosphere. The vow book '
                          'is clearly visible and is the main focus of the photo, while the lush greenery, soft '
                          'flowers, and natural garden backdrop add background and warmth. Bright natural daylight '
                          'illuminates the scene, and the background is gently blurred with subtle depth of field to '
                          'create a professional, editor-quality look. A standout product photo on Etsy.\n'
                          '\n'
                          'IMPORTANT: The EXACT shape of the vow book is retained from the reference photo. The linen '
                          'texture, color palette, embroidery style, cover layout, proportions, and overall '
                          'handcrafted look are also preserved. Do not edit the vow book itself – only recreate the '
                          'surrounding background and the life-related scenes around it.\n'
                          '\n'
                          'STYLE: Handmade product photography, romantic wedding lifestyle, soft natural lighting, '
                          'editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                          '\n'
                          'AVOID: altering the vow book design, changing the embroidery, mass production style, harsh '
                          'studio lighting, cluttered background, distracting props, AI errors, text overlays, '
                          'watermarks.'),
                         ('Gift box',
                          'Gift box',
                          'This product image of the handmade wedding vow book is taken from a reference photo. The '
                          'bride and groom are photographed in a close-up of a romantic wedding portrait, gently '
                          'kissing while each holds a vow book in front of them. The couple are dressed in elegant '
                          'wedding attire, creating an intimate and touching atmosphere. The vow books are prominently '
                          'displayed in the foreground and are the main focus of the photo, while the couple and the '
                          'wedding backdrop are subtly designed to add warmth and storytelling. Soft natural light '
                          'illuminates the scene, and the clean, airy, slightly blurred background with a gentle depth '
                          'of field creates a sophisticated, almost editorial look. A standout product image on Etsy.\n'
                          '\n'
                          'IMPORTANT: The EXACT shape of the vow book from the reference photo is preserved. The linen '
                          'texture, color palette, embroidery style, cover layout, proportions, and overall '
                          'handcrafted appearance are also retained. Do not edit the vow books themselves – only '
                          'recreate the surrounding background and the everyday life setting.\n'
                          '\n'
                          'STYLE: Handmade product photography, romantic wedding lifestyle, soft natural lighting, '
                          'editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                          '\n'
                          'AVOID: altering the vow book design, changing the embroidery, mass production style, harsh '
                          'studio lighting, cluttered background, distracting props, AI errors, text overlays, '
                          'watermarks.'),
                         ('Product display',
                          '2 cuốn bìa rõ cả 2',
                          "This lifestyle photograph captures a close-up of a woman's hands meticulously embroidering "
                          "the Bride's Vow motif on a circular embroidery hoop. The image focuses on the delicate, "
                          'precise embroidery process, showing the thread being pulled through the fabric and the '
                          'needle holes threaded. The hands are depicted in a natural, relaxed posture, highlighting '
                          'the skill and meticulousness. The surrounding space is decorated in a minimalist and '
                          'handcrafted style, including neutral-colored embroidery thread, a small pair of scissors, '
                          'and a few dried flowers. Soft natural light from the side accentuates the texture of the '
                          'fabric and thread, creating a warm, artistic atmosphere.\n'
                          '\n'
                          'IMPORTANT: Maintain the EXACT shape of the embroidery motif from the reference image. Keep '
                          'the fabric texture, embroidery pattern, thread color, needle placement, and proportions '
                          'unchanged. Do not alter the embroidery motif or stitch details—simply create a new context '
                          'around it.\n'
                          '\n'
                          'STYLE: Handcrafted product photography, soft natural lighting, high-quality editing, modern '
                          'minimalist aesthetics in the Etsy style, 1:1 square aspect ratio.\n'
                          '\n'
                          'AVOID: Incorrect needle placement, unthreaded needles, blurry images. Errors such as uneven '
                          'stitching, overly stylized hands, cluttered backgrounds, AI errors, text overlapping '
                          'images, blurry images.'),
                         ('Lifestyle',
                          'Cầm tại bàn tiệc cưới',
                          'This product image of the handcrafted wedding vow book is taken from a reference photo. Two '
                          "vow books are placed in the center, between the bride's elegant high heels and the groom's "
                          'classic dress shoes, creating a sophisticated and romantic composition in the style of a '
                          'flat wedding photoshoot. Soft lace is styled around the scene, adding texture and the '
                          "bride's elegance. The image is taken from a low angle, creating depth in the composition "
                          'and highlighting the vow books. Soft, elegant lighting illuminates the entire scene, '
                          'highlighting the linen texture and the handcrafted quality of the books. The clean, '
                          'elegant, and subtly styled background, with its delicate depth of field, creates a '
                          'professional, editorial look. A standout product photo on Etsy. \n'
                          '\n'
                          'IMPORTANT: The EXACT shape of the vow books from the reference photo is preserved. The '
                          'linen texture, color palette, embroidery style, cover layout, proportions, and overall '
                          'handcrafted look are also preserved. Do not edit the vow books themselves – only recreate '
                          'the surrounding background and the everyday scenes around them. \n'
                          '\n'
                          'STYLE: Handmade product photography, romantic wedding style, soft and elegant lighting, '
                          'professional image quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio. \n'
                          '\n'
                          'AVOID: altering the vow book design, changing embroidery patterns, mass-produced images, '
                          'harsh studio lighting, cluttered backgrounds, distracting props, AI errors, text overlays, '
                          'watermarks.'))},
 'ring_bearer_pillow': {'display_name': 'Ring Bearer Pillow',
                        'aliases': ('Ring Bearer Pillow',
                                    'ring bearer pillow',
                                    'wedding ring pillow',
                                    'ring pillow',
                                    'gối nhẫn',
                                    'goi nhan'),
                        'lock': 'the main product must remain the same ring bearer pillow with the exact cushion '
                                'shape, fabric surface, embroidery/floral motif placement, ribbon/ring attachment area '
                                'if present, soft volume, seams, and wedding ceremony scale from the source image',
                        'shots': (('Product display',
                                   'Đứng trên gỗ sơn trắng',
                                   'This product image of a handcrafted wedding ring pillow is taken from a reference '
                                   'photo. The pillow is displayed standing on a clean white wooden surface in a soft '
                                   'and elegant interior space. It is decorated with delicate wedding-inspired details '
                                   'such as gentle flowers and foliage, soft linen fabric, and a few small stitches or '
                                   'decorative motifs arranged around it, with a white voile overlay behind, creating '
                                   'a romantic and handcrafted atmosphere. The ribbon and wedding rings are clearly '
                                   'visible, while the pillow remains the main focal point of the photo. Soft natural '
                                   'light illuminates the scene, highlighting the fabric texture and handcrafted '
                                   'quality. The clean, airy, and slightly blurred background with a gentle depth of '
                                   'field creates a sophisticated, editorial look. A standout product photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the ring pillow from the reference photo is '
                                   'retained. The fabric texture, color palette, embroidery style, ribbon details, '
                                   'proportions, and overall handcrafted look are preserved. No need to edit the ring '
                                   'cushion – just recreate the background and surrounding scenery. \n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, romantic wedding style, soft natural '
                                   'lighting, professional image quality, modern minimalist Etsy aesthetic, 1:1 square '
                                   'aspect ratio. \n'
                                   '\n'
                                   'AVOID: altering the ring cushion design, changing embroidery patterns, '
                                   'mass-produced images, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Product display',
                                   'Kế hộp nhẫn gỗ mở',
                                   'This product image of a handcrafted wedding ring pillow is taken from a reference '
                                   'photo. A ring pillow sits upright on a clean table in an elegant and serene '
                                   'interior. Beside it is an open wooden wedding ring box containing two wedding '
                                   'rings, along with delicate natural decorations such as eucalyptus branches, dried '
                                   'flowers, and a few smooth stones arranged around it to create a tranquil, romantic '
                                   'atmosphere. Soft natural light from a nearby window highlights the fabric and the '
                                   'handcrafted beauty of the pillow. The ring pillow is the focal point of the photo, '
                                   'while the surrounding items add warmth and tell a subtle story. The clean, airy, '
                                   'and slightly blurred background with a gentle depth of field creates a '
                                   'professional, edited look. A standout product photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the ring pillow from the reference photo is '
                                   'preserved. Maintain the original fabric, color palette, embroidery style, ribbon '
                                   'details, proportions, and overall handcrafted look. Do not edit the ring pillow '
                                   'itself – only recreate the background and surrounding scenery. \n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, romantic wedding style, soft natural '
                                   'lighting, professional image quality, modern minimalist Etsy aesthetic, 1:1 square '
                                   'aspect ratio. \n'
                                   '\n'
                                   'AVOID: altering the ring pillow design, changing the embroidery pattern, '
                                   'mass-produced images, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Product display',
                                   '3 chiếc trên kệ tường',
                                   'This product image of handcrafted wedding ring pillows is taken from a reference '
                                   'photo. Three ring pillows are displayed on three separate wall-mounted wooden '
                                   'shelves in an elegant interior space, with the middle pillow positioned slightly '
                                   'higher for a balanced composition. Each pillow shares the same embroidery style '
                                   'and overall design, but with different personalized names, and each is presented '
                                   'in a different color. Soft decorative details such as delicate dried flowers and '
                                   'sheer voile fabric are arranged around them, creating a warm, romantic, and '
                                   'sophisticated wedding atmosphere. The ring pillows are the main focal point in the '
                                   'center of the photo, while the surrounding decorations add balance and tell a '
                                   'subtle story. Gentle natural light illuminates the scene, highlighting the fabric '
                                   'texture, ribbon details, and handcrafted quality. The clean, warm, minimalist, and '
                                   'slightly muted background creates a professional, editorial look. A standout '
                                   'product photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape of the ring pillow from the reference image. '
                                   'Keep the fabric texture, embroidery style, ribbon details, proportions, and '
                                   'overall handcrafted look. Showcase three pillows with the same layout and '
                                   'embroidery, but in three different colors, each with a different personalized '
                                   'name. Do not alter the structure or style of the pillows – simply recreate the '
                                   'context and surrounding setting. \n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, romantic wedding style, soft natural '
                                   'lighting, editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect '
                                   'ratio. \n'
                                   '\n'
                                   'AVOID: altering the pillow shape, changing the embroidery layout, changing the '
                                   'ribbon style, mass-produced look, harsh studio lighting, cluttered background, '
                                   'distracting props, AI errors, text overlays, watermarks.'),
                                  ('Product display',
                                   'Trên vải satin trắng',
                                   'This product image of the handmade wedding ring pillow is taken from a reference '
                                   'photo. The ring pillow is displayed on a soft white satin fabric in an elegant '
                                   'interior space. Alongside it are romantic wedding-inspired details such as a '
                                   'wedding bouquet (a bouquet of fresh flowers similar to the embroidered flowers on '
                                   'the ring pillow), a sealed envelope, and a few scattered petals or delicate floral '
                                   'accents, creating a graceful and emotional atmosphere. The ring pillow is the '
                                   'central focal point of the photo, while the surrounding items add warmth and tell '
                                   'a subtle story. Soft natural light illuminates the scene, highlighting the fabric '
                                   'texture, ribbon details, and handcrafted quality. The composition is styled like '
                                   'an elegant flat photograph with a clean, airy background and a light, editorial '
                                   'feel. A standout product photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the ring pillow from the reference photo is '
                                   'preserved. Maintain the original fabric texture, color palette, embroidery style, '
                                   'ribbon details, proportions, and overall handcrafted look. Do not edit the ring '
                                   'pillow itself – only recreate the surrounding background and the life-like '
                                   'setting. \n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, romantic wedding style, soft natural '
                                   'lighting, professional image quality, modern minimalist Etsy aesthetic, 1:1 square '
                                   'aspect ratio. \n'
                                   '\n'
                                   'AVOID: altering the ring pillow design, changing the embroidery pattern, '
                                   'mass-produced images, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Product display',
                                   'Trên giá gỗ ngoài trời',
                                   'This product image of a handcrafted wedding ring pillow is taken from a reference '
                                   'photo. A ring pillow sits upright on a small wooden stand on a rustic wooden table '
                                   'in an elegant outdoor wedding setting. Surrounding the pillow are romantic '
                                   'wedding-inspired details such as a wedding bouquet matching the embroidery on the '
                                   'ring pillow, candles, a wedding cake, and a vow book, creating a warm and graceful '
                                   'atmosphere. Soft, natural sunset light illuminates the scene, highlighting the '
                                   'fabric texture, ribbon details, and the handcrafted quality of the pillow. The '
                                   'ring pillow is the central focal point of the photo, while the surrounding '
                                   'decorations add balance and tell a subtle story. The backdrop is an outdoor '
                                   'garden, gently blurred with just the right depth of field to create a '
                                   'professional, magazine-worthy look. A standout product photo on Etsy.\n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the ring pillow from the reference photo is '
                                   'preserved. Maintain the original fabric texture, color palette, embroidery style, '
                                   'ribbon details, proportions, and overall handcrafted look. Do not edit the ring '
                                   'pillow itself – only recreate the background and surrounding scenery.\n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, romantic wedding style, soft natural '
                                   'lighting, professional image quality, modern minimalist Etsy aesthetic, 1:1 square '
                                   'aspect ratio.\n'
                                   '\n'
                                   'AVOID: altering the ring pillow design, changing the embroidery pattern, '
                                   'mass-produced images, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Cận thêu tay',
                                   'Cận thêu hoa',
                                   'Take a close-up photograph of the embroidered floral pattern on the fabric ring '
                                   'cushion from the reference image, focusing on the exquisite hand-embroidered '
                                   'details, with clear threads and beautiful stitching, making the embroidery as '
                                   'visible as possible. The fabric ring cushion should be the main focal point, '
                                   'highlighting the embroidery and stitching. Soft, natural light from the side will '
                                   'emphasize the depth of the embroidery, with a shallow depth of field to create a '
                                   'hazy effect around the fabric. The fabric should be neutral and clean-colored, and '
                                   'the handcrafted details must be clearly visible, highlighting the quality of the '
                                   'product. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape of the fabric ring cushion from the reference '
                                   'image. Preserve the fabric material, embroidery details, thread color, stitching, '
                                   'proportions, and handcrafted characteristics. Do not alter the ring cushion in any '
                                   'way—only enlarge the existing embroidery details. \n'
                                   '\n'
                                   'STYLE: Close-up photos of handcrafted products, soft natural lighting, '
                                   'high-quality editing, modern minimalist aesthetics in the Etsy style, 1:1 square '
                                   'aspect ratio. \n'
                                   '\n'
                                   'AVOID: blurry stitching, images that look like they were created by machines, '
                                   'edited embroidery patterns, harsh lighting, overexposed images, bright spots, AI '
                                   'errors, text overlapping images, blurry images.'),
                                  ('Gift box',
                                   'Gift box',
                                   'This product image of a handcrafted wedding ring pillow is taken from a reference '
                                   'photo. The ring pillow is displayed inside an elegant gift box in a soft and '
                                   'sophisticated interior setting. The gift box opens gently to reveal the pillow, '
                                   'creating a beautiful, thoughtful, romantic presentation suitable for gifting. Soft '
                                   'decorative details such as tissue paper, ribbons, or delicate wedding-inspired '
                                   'accents can surround the box, adding warmth and a charming handcrafted atmosphere. '
                                   'Gentle natural light illuminates the scene, highlighting the fabric texture, '
                                   'ribbon details, and overall handcrafted quality of the pillow. The ring pillow '
                                   'remains the main focus of the image, while the surrounding elements add balance '
                                   'and subtle storytelling. The clean, airy, and slightly blurred background with a '
                                   'gentle depth of field creates a professional, editorial look. A standout product '
                                   'photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape of the ring pillow from the reference image. '
                                   'Keep the fabric texture, color palette, embroidery style, ribbon details, '
                                   'proportions, and overall handcrafted look. Do not edit the ring pillow itself – '
                                   'only recreate the surrounding background and gift box presentation. \n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, romantic wedding style, soft natural '
                                   'lighting, professional image quality, modern minimalist Etsy aesthetic, 1:1 square '
                                   'aspect ratio. \n'
                                   '\n'
                                   'AVOID: altering the ring pillow design, changing embroidery patterns, '
                                   'mass-produced images, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Lifestyle',
                                   'Cô dâu cầm nhẹ nhàng',
                                   'This product image of the handmade wedding ring pillow is taken from a reference '
                                   'photo. In the photo, the bride gently cradles the pillow with both hands in an '
                                   'elegant and tender wedding setting, the pillow fitting comfortably in her palms '
                                   '(not too large). The wedding dress and veil create a romantic and graceful '
                                   'atmosphere, while the pillow remains the focal point of the photo. The composition '
                                   "is intimate and delicate, with the bride's hands highlighting the pillow, "
                                   'emphasizing its handcrafted quality and sentimental significance. Soft natural '
                                   'light illuminates the scene, highlighting the fabric texture, ribbon details, and '
                                   'overall craftsmanship. The clean, airy, and slightly blurred background with just '
                                   'the right depth of field creates a professional look worthy of magazine coverage. '
                                   'A standout product photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the ring pillow from the reference photo is '
                                   'retained. The fabric texture, color palette, embroidery style, ribbon details, '
                                   'proportions, and overall handcrafted look are preserved. No editing of the ring '
                                   'cushion is required – only the background and surrounding scenery are recreated. \n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, romantic wedding style, soft natural '
                                   'lighting, edited image quality, modern minimalist Etsy aesthetic, 1:1 square '
                                   'aspect ratio. \n'
                                   '\n'
                                   'AVOID: altering the ring cushion design, changing embroidery patterns, '
                                   'mass-produced photos, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Product display',
                                   'Trong xe ngựa gỗ miniature',
                                   'This product image of a handmade wedding ring pillow is taken from a reference '
                                   'photo. The ring pillow is displayed inside a small, rustic wooden carriage in an '
                                   'elegant and light interior space. The carriage is lined with light, airy voile '
                                   'fabric, and delicate dried flowers are arranged around the pillow to create a '
                                   'warm, romantic, and poetic wedding atmosphere. The ribbons and wedding rings are '
                                   'clearly visible, while the ring pillow remains the main focal point of the photo. '
                                   'Warm, soft natural light illuminates the scene, highlighting the fabric texture, '
                                   'ribbon details, and overall craftsmanship. The background is subtly styled with '
                                   'rustic wooden flooring and a moderate depth of field to create a professional, '
                                   'magazine-style look. A standout product photo on Etsy.\n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the ring pillow from the reference photo is '
                                   'retained. The fabric texture, color palette, embroidery style, ribbon details, '
                                   'proportions, and overall handcrafted appearance are also preserved. Do not edit '
                                   'the ring pillow itself – only recreate the surrounding background and the '
                                   'surrounding scene.\n'
                                   '\n'
                                   'STYLE: Handmade product photography, romantic wedding style, soft natural '
                                   'lighting, professional image quality, modern minimalist Etsy aesthetic, 1:1 square '
                                   'aspect ratio.\n'
                                   '\n'
                                   'AVOID: altering the ring pillow design, changing the embroidery pattern, '
                                   'mass-produced images, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Lifestyle',
                                   'Đôi uyên ương cùng cầm',
                                   'This product image of a handcrafted wedding ring pillow is taken from a reference '
                                   'photo. The bride and groom are shown sitting next to each other in an elegant '
                                   'indoor wedding setting, gently holding the ring pillow between them (a small, not '
                                   'large, ring pillow). The couple are dressed in sophisticated wedding attire, '
                                   'creating a romantic and intimate atmosphere. The ring pillow is the central focal '
                                   "point of the photo, while the bride's lace dress, the groom's formal suit, and "
                                   'meticulously arranged wedding details such as the bouquet and classic furniture in '
                                   'the background add warmth and tell a story. Soft natural light illuminates the '
                                   'scene, highlighting the fabric texture, ribbon details, and overall craftsmanship '
                                   'of the pillow. The clean, airy background is prepared with just the right depth of '
                                   'field to create a professional look worthy of magazine coverage. A standout '
                                   'product photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the ring pillow from the reference image is '
                                   'preserved. Maintain the fabric texture, color palette, embroidery style, ribbon '
                                   'details, proportions, and overall handcrafted look. Do not edit the ring pillow '
                                   'itself – only recreate the surrounding background and scene as realistically as '
                                   'possible. \n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, romantic wedding style, soft natural '
                                   'lighting, editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect '
                                   'ratio. \n'
                                   '\n'
                                   'AVOID: altering the ring pillow design, changing the embroidery pattern, '
                                   'mass-produced photos, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Lifestyle',
                                   'Cận đôi tay cầm gối',
                                   'This product image of the handmade wedding ring pillow is taken from a reference '
                                   'photo. A close-up shows the bride and groom gently cradling the ring pillow in '
                                   'both hands in an elegant wedding setting. The pillow is prominently placed in the '
                                   'center of the image, creating an intimate and meaningful composition. The ring '
                                   "pillow remains the main focus, while the couple's wedding attire and floral "
                                   'backdrop are subtly blurred, adding warmth, romance, and a delicate story. Soft '
                                   'natural light illuminates the scene, highlighting the fabric texture, ribbon '
                                   'details, and overall craftsmanship of the pillow. The clean, airy, and subtly '
                                   'blurred background with just the right depth of field creates a professional, '
                                   'magazine-worthy look. A standout product photo on Etsy. \n'
                                   '\n'
                                   'IMPORTANT: The EXACT shape of the ring pillow from the reference photo is '
                                   'preserved. The fabric texture, color palette, embroidery style, ribbon details, '
                                   'proportions, and overall handcrafted appearance are also retained. Do not edit the '
                                   'ring pillow itself – only recreate the surrounding background and the everyday '
                                   'scene around it. \n'
                                   '\n'
                                   'STYLE: Handmade product photography, romantic wedding style, soft natural '
                                   'lighting, editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect '
                                   'ratio. \n'
                                   '\n'
                                   'AVOID: altering the ring pillow design, changing the embroidery pattern, '
                                   'mass-produced images, harsh studio lighting, cluttered backgrounds, distracting '
                                   'props, AI errors, text overlays, watermarks.'),
                                  ('Quy trình',
                                   'Process — Tay thêu cận',
                                   'This product image of the handmade wedding ring pillow is taken from a reference '
                                   'photo. The close-up shows skilled hands embroidering on fabric in a circular '
                                   'embroidery hoop, with the same embroidery pattern as on the sample ring pillow. '
                                   'Surrounding the work area are delicate sewing materials such as embroidery thread, '
                                   'small scissors, fabric, and a few dried flowers arranged gently, creating a warm, '
                                   'handcrafted, and intimate atmosphere. Soft, natural yellow light illuminates the '
                                   'scene, highlighting the craftsmanship, fabric texture, and embroidery details. The '
                                   'embroidery remains the main focus of the photo, while the surrounding tools and '
                                   'decorations add context and story. The clean, warm, and slightly blurred '
                                   'background with depth of field creates a professional look. \n'
                                   '\n'
                                   'IMPORTANT: The exact shape and handcrafted appearance of the wedding ring pillow '
                                   'design from the reference photo is preserved. The fabric texture, embroidery '
                                   'style, color palette, proportions, and overall handcraft quality are maintained. '
                                   'Do not alter the embroidery layout to suit a different design concept – simply '
                                   'recreate the surrounding background and handcrafted setting. \n'
                                   '\n'
                                   'STYLE: Handcrafted product photography, detailed embroidery processing, soft '
                                   'natural lighting, professional image quality, modern minimalist Etsy style, 1:1 '
                                   'square aspect ratio. \n'
                                   '\n'
                                   'AVOID: Empty needle holes, misplaced embroidery stitches, inaccurate thread '
                                   'colors, altered ring pillow designs, altered embroidery patterns, mass-produced '
                                   'images, harsh studio lighting, cluttered backgrounds, distracting props, AI '
                                   'errors, text overlaying images, watermarks.'))},
 'guest_book': {'display_name': 'Guest Book',
                'aliases': ('Guest Book',
                            'guest book',
                            'wedding guest book',
                            'embroidered guest book',
                            'photo album',
                            'wedding photo album',
                            'fabric photo album',
                            'embroidered photo album',
                            'scrapbook',
                            'wedding scrapbook',
                            'memory book',
                            'sổ ký tên',
                            'so ky ten',
                            'sổ khách',
                            'so khach'),
                'lock': 'the main product must remain the same fabric-covered wedding guest book with the exact book '
                        'shape, cover material, embroidery placement, spine/edge construction, lettering/motif style, '
                        'and elegant keepsake scale from the source image',
                'shots': (('Product display',
                           'Trên vải trắng + props cưới',
                           'This product image of a handmade wedding scrapbook is taken from a reference photo. The '
                           'scrapbook is displayed on a soft white fabric in an elegant interior setting. Alongside it '
                           'are romantic wedding-inspired details such as a wedding bouquet, wedding rings, '
                           'invitations, and scattered flower petals, creating a charming and emotional atmosphere. '
                           'The scrapbook is the central focal point of the image, while the surrounding items add '
                           'warmth and tell a subtle story. Soft natural light illuminates the scene, highlighting the '
                           'fabric texture, craftsmanship, and elegant cover presentation. The composition is styled '
                           'like an elegant flat photograph with a clean, airy background and a light, editorial feel. '
                           'A standout product image on Etsy.\n'
                           '\n'
                           'IMPORTANT: The EXACT shape of the scrapbook from the reference photo is preserved. The '
                           'linen texture, color palette, embroidery style, cover layout, proportions, and overall '
                           'handcrafted look are also retained. Do not edit the scrapbook – only recreate the '
                           'surrounding background and the life-like setting.\n'
                           '\n'
                           'STYLE: Handmade product photography, romantic wedding style, soft natural lighting, '
                           'editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                           '\n'
                           'AVOID: altering the scrapbook design, changing the embroidery, mass-production style, '
                           'harsh studio lighting, cluttered background, distracting props, AI errors, text overlays, '
                           'watermarks.'),
                          ('Cận thêu tay',
                           'Cận thêu tay',
                           'Take a close-up photo of the fabric notebook from the reference image, focusing on the '
                           'exquisite hand-embroidered details, with clear threads and beautiful stitching. The fabric '
                           'notebook should be the main focal point, highlighting the embroidery and stitching. Soft, '
                           'natural light from the side will emphasize the depth of the embroidery, with a shallow '
                           'depth of field to create a hazy effect around the fabric. The fabric should be neutral and '
                           'clean-colored, and the handcrafted details must be clearly visible, highlighting the '
                           'quality of the product.\n'
                           '\n'
                           'IMPORTANT: Maintain the EXACT shape of the fabric notebook from the reference image. '
                           'Preserve the fabric material, embroidery details, thread color, stitching, proportions, '
                           'and handcrafted characteristics. Do not alter the notebook in any way—only enlarge the '
                           'existing embroidery details.\n'
                           '\n'
                           'STYLE: Close-up of the handcrafted product, soft natural light, high-quality editing, '
                           'modern minimalist Etsy-style aesthetic, square aspect ratio. 1:1.\n'
                           '\n'
                           'AVOID: blurry seams, images that look machine-generated, altered embroidery patterns, '
                           'harsh lighting, overexposed images, highlights, AI errors, text overlaid on images, '
                           'watermarks.'),
                          ('Product display',
                           'Dựng trên giá gỗ nhỏ',
                           'This product photo of a handmade wedding scrapbook is taken from a reference image. The '
                           'scrapbook is placed upright on a small wooden stand on a clean white table in an elegant '
                           'wedding setting. Surrounding the scrapbook are romantic wedding-inspired details such as a '
                           'soft bouquet resembling the embroidered flowers on the scrapbook, an open wooden ring box, '
                           'candles, and delicate lace accents, creating a graceful and sophisticated atmosphere. The '
                           'scrapbook is the main focus of the photo, while the surrounding decorations add warmth and '
                           'tell a subtle story. Soft natural light illuminates the scene, highlighting the linen '
                           'texture, the craftsmanship, and the elegant presentation of the cover. The clean, airy, '
                           'and slightly blurred background with just the right depth of field creates a professional, '
                           'magazine-style look. A standout product photo on Etsy. \n'
                           '\n'
                           'IMPORTANT: The EXACT shape of the scrapbook from the reference image is preserved. '
                           'Maintain the original linen texture, color palette, embroidery style, cover layout, '
                           'proportions, and overall handcrafted look. Do not edit the scrapbook – only recreate the '
                           'surrounding background and the life-like setting. \n'
                           '\n'
                           'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                           'professional image quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio. \n'
                           '\n'
                           'AVOID: altering the scrapbook design, changing embroidery patterns, mass production style, '
                           'harsh studio lighting, cluttered backgrounds, distracting props, AI errors, text overlays, '
                           'watermarks.'),
                          ('Lifestyle',
                           'Cô dâu cầm gracefully',
                           'This product photo of a handcrafted wedding scrapbook is taken from a reference image. In '
                           'a gentle and elegant wedding setting, the bride is shown holding the scrapbook gracefully. '
                           'She wears a romantic off-the-shoulder wedding dress, creating a charming and sophisticated '
                           'atmosphere, while the scrapbook remains the focal point of the photo. The composition is '
                           'intimate and refined, with the bride clearly displaying the scrapbook to emphasize its '
                           'handcrafted quality and sentimental value. Delicate floral decorations in the background '
                           'add warmth and a refined wedding ambiance. Soft natural light illuminates the scene, '
                           'highlighting the fabric texture, craftsmanship, and elegant presentation of the cover. The '
                           'clean, airy, and subtly blurred background with just the right depth of field creates a '
                           'professional, magazine-style look. A standout product photo on Etsy.\n'
                           '\n'
                           'IMPORTANT: The EXACT shape of the scrapbook from the reference image is preserved. '
                           'Maintain the original fabric texture, color palette, embroidery style, cover layout, '
                           'proportions, and overall handcrafted look. Do not edit the scrapbook – only recreate the '
                           'surrounding background and the life-like setting.\n'
                           '\n'
                           'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                           'editorial image quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                           '\n'
                           'AVOID: altering the scrapbook design, changing embroidery patterns, mass-produced images, '
                           'harsh studio lighting, cluttered backgrounds, distracting props, AI errors, text overlays, '
                           'watermarks.'),
                          ('Lifestyle',
                           'Đôi uyên ương ngồi ngoài trời',
                           'This product image is a handcrafted wedding photo album taken from a reference photo. The '
                           'bride and groom are shown sitting close together in a romantic outdoor wedding setting, '
                           'gently holding the album in front of them. The album is the main focus of the photo, while '
                           "the couple's elegant wedding attire and the hazy flower garden background create a warm, "
                           'intimate, and sophisticated atmosphere. Soft natural sunlight illuminates the scene, '
                           'highlighting the linen fabric, the craftsmanship, and the elegant presentation of the '
                           'cover. The composition evokes a romantic and refined feel, with a soft depth of field that '
                           'focuses attention on the album while adding charm to the wedding story. A featured product '
                           'image on Etsy. \n'
                           '\n'
                           'IMPORTANT: The EXACT shape of the album from the reference photo is preserved. The linen '
                           'fabric, color palette, embroidery style, cover layout, proportions, and overall '
                           'handcrafted appearance are also preserved. Do not edit the album – only recreate the '
                           'surrounding background and scenes related to life. \n'
                           '\n'
                           'STYLE: Handmade product photography, romantic wedding lifestyle, soft natural lighting, '
                           'editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio. \n'
                           '\n'
                           'AVOID: altering the album design, changing embroidery, mass production style, overly harsh '
                           'studio lighting, cluttered background, distracting props, AI errors, text overlays, '
                           'watermarks.'),
                          ('Product display',
                           'Trên bàn gỗ sáng + décor',
                           'The product image of this handcrafted wedding photo album is taken from a reference photo. '
                           'The album is placed on a light-colored wooden table in an elegant layout, either flat or '
                           'tilted, with one hand gently opening the cover, creating a natural feel. The album remains '
                           'the main focal point, prominently positioned at the center of the composition. Surrounding '
                           "it are delicate wedding-inspired decorative elements such as white roses, baby's breath, "
                           'eucalyptus leaves, voile ribbon, and a few scattered pearls, creating a romantic and '
                           'sophisticated atmosphere. The minimalist, clean, and bright background highlights the '
                           'handcrafted beauty of the album without distraction. \n'
                           '\n'
                           'Soft natural light illuminates the scene, highlighting the linen texture, delicate '
                           "embroidery, and the quality of the album's craftsmanship. The bright, airy, and elegant "
                           'background, with its serene wedding-inspired beauty, perfectly suits a high-end product on '
                           'Etsy. The composition creates a feeling of sophistication, femininity, romance, and '
                           'luxury. A featured product photo on Etsy. \n'
                           '\n'
                           'IMPORTANT: Maintain the EXACT shape of the album. Based on the reference photo. Keep the '
                           'linen fabric, color palette, embroidery style, cover layout, proportions, and overall look '
                           'of the handmade product. Do not edit the photo album or the detailed embroidery '
                           'description. Simply recreate the background and surrounding environment in a new style. \n'
                           '\n'
                           'STYLE: Handmade product photography, romantic wedding style, soft natural lighting, '
                           'editorial quality, modern minimalist Etsy aesthetic, 1:1 square aspect ratio. \n'
                           '\n'
                           'AVOID: Writing detailed embroidery instructions, changing the photo album design, changing '
                           'the photo album shape, harsh studio lighting, cluttered background, distracting props, '
                           'mass-produced look, AI errors, text overlays, watermarks.'),
                          ('Lifestyle',
                           'Đôi uyên ương đứng ngoài trời',
                           'This product photo of a handcrafted wedding scrapbook is taken from a reference image. The '
                           'bride and groom stand close together outdoors in a romantic garden wedding setting, softly '
                           'illuminated by warm natural sunlight. They hold the scrapbook together, holding it towards '
                           'the camera at chest level, making it the focal point of the photo. The bride wears an '
                           'elegant white lace wedding dress, while the groom wears a meticulously tailored light gray '
                           'suit with a boutonnière. Their faces are partially visible, but the main focus remains on '
                           'the scrapbook and its handcrafted beauty. \n'
                           '\n'
                           'The backdrop evokes a dreamy garden wedding atmosphere with soft greenery, subtle floral '
                           'details, and elegant wooden chairs, creating a refined and romantic wedding mood. The '
                           'composition looks natural, polished, and editorial, with the scrapbook placed prominently '
                           "in the couple's hands. The setting should evoke intimacy, love, and the high-end aesthetic "
                           'of a handcrafted wedding. \n'
                           '\n'
                           'The soft, natural yellow light highlights the linen texture, the delicate embroidery, and '
                           'the overall craftsmanship of the scrapbook. The background should be slightly blurred to '
                           'maintain focus on the product while preserving the elegant outdoor wedding setting. A '
                           'standout lifestyle product photo on Etsy. \n'
                           '\n'
                           'IMPORTANT: Keep the EXACT shape of the scrapbook as in the reference photo. Maintain the '
                           'linen material, color palette, embroidery style, cover layout, proportions, and overall '
                           'handcrafted look. Do not edit the scrapbook or detail the embroidery. Simply recreate a '
                           'new lifestyle setting and environment. \n'
                           '\n'
                           'STYLE: Handcrafted product photography, romantic wedding photo, soft natural light, '
                           'editorial quality, elegant garden setting, modern Etsy aesthetic, 1:1 square aspect '
                           'ratio. \n'
                           '\n'
                           'AVOID: Writing detailed embroidery instructions, changing scrapbook design, changing '
                           'scrapbook shape, harsh lighting, cluttered background, distracting props, stiff posing, '
                           'mass-produced look, AI errors, text overlays, watermarks.'),
                          ('Product display',
                           '3 cuốn flat lay trên tulle',
                           'Product photos of three handcrafted wedding scrapbooks are taken from reference images. '
                           'The three scrapbooks are arranged in a flat, elegant layout on a thin white tulle '
                           'background. One scrapbook is placed in the middle at the top, and the other two below, '
                           'forming a balanced triangle. Each scrapbook shares the same embroidery style and overall '
                           'layout, but each has a different linen cover color and personalized names and wedding '
                           'dates. The embroidery pattern should be kept general and not overly detailed, so this '
                           'suggestion can be used for many different scrapbook designs. \n'
                           '\n'
                           'Soft natural light illuminates the scene, highlighting the linen texture of each scrapbook '
                           'cover and the delicate handcrafted embroidery. The lighting should feel bright, clean, and '
                           'gentle, with minimal harsh shadows. The layout ensures that all three scrapbooks are '
                           'clearly visible and equally prominent, while decorative elements play only a secondary and '
                           'supporting role. \n'
                           '\n'
                           'IMPORTANT: Maintain the EXACT shape of the scrapbooks from the reference image. Keep the '
                           'linen fabric, embroidery style, handcrafted look, and overall cover proportions and '
                           'layout. Do not describe the embroidery details. Simply mention that the scrapbooks feature '
                           'personalized embroidery and handcrafted designs. The three scrapbooks should have '
                           'different cover colors and names, but maintain a consistent visual style and product '
                           'presentation. \n'
                           '\n'
                           'STYLE: Handcrafted product photography, romantic flat layout for weddings, soft natural '
                           'lighting, elegant Etsy aesthetic, clean editorial style, airy layout, high-end handcrafted '
                           'look, 1:1 square aspect ratio. \n'
                           '\n'
                           'AVOID: Writing detailed embroidery instructions, altering the scrapbook shape, changing '
                           'the overall scrapbook proportions, cluttered styling, dark lighting, harsh shadows, '
                           'distracting props, text overlays, watermarks, AI errors.'),
                          ('Gift box',
                           'Gift box',
                           'Create a high-quality, handcrafted product photo of a personalized wedding guest book as a '
                           'reference, neatly placed in an elegant gift box. The guest book is the main focus, resting '
                           'on soft silk paper or delicate tulle, with the box opened to showcase the product. The '
                           'cover is made of linen with hand-embroidered motifs. Surround the box with a few romantic '
                           "wedding accessories such as silk ribbons, baby's breath flowers, pearls, or a small "
                           'bouquet. Use soft, natural lighting, a clean, airy background, and a subtly romantic style '
                           'to highlight the linen material, the handcrafted feel, and the high-end look of the gift. '
                           'Keep the layout elegant, minimalist, and suitable for Etsy product photography.'))},
 'bouquet_ribbon': {'display_name': 'Bouquet Ribbon',
                    'aliases': ('Bouquet Ribbon',
                                'bouquet ribbon',
                                'bridal bouquet ribbon',
                                'wedding ribbon',
                                'embroidered ribbon',
                                'ribbon cưới',
                                'ribbon cuoi',
                                'dải ruy băng',
                                'dai ruy bang'),
                    'lock': 'the main product must remain the same long embroidered bouquet ribbon with the exact '
                            'ribbon width, fabric drape, stitched lettering or motif placement, edge finish, color, '
                            'and wedding accessory scale from the source image',
                    'shots': (('Lifestyle',
                               'Ribbon trong bó hoa cưới',
                               'Create a high-quality, handcrafted product image featuring a vibrant wedding bouquet '
                               'incorporating various flowers in similar or matching colors to the embroidered ribbon. '
                               'The bouquet is tied with a personalized embroidered ribbon bow and placed on a dark '
                               'tray covered with soft, elegant white voile fabric. Keep the embroidered ribbon as the '
                               'main focal point, clearly visible and not obscured, with the embroidery identical to '
                               'the original image, surrounded by a minimalist wedding backdrop. Add delicate '
                               'decorative details such as soft petals, greeting cards, wax-sealed kraft paper '
                               'envelopes, and sheer voile fabric. The setting should evoke a romantic, gentle, and '
                               'handcrafted feel with soft lighting and a harmonious pastel color palette. \n'
                               '\n'
                               'Use soft natural light from a window shining from the upper left to create subtle '
                               'shadows and highlight the fabric texture, ribbon weave, floral details, and '
                               'embroidery. The backdrop should be slightly muted and have warm tones, accentuating '
                               "the embroidered ribbon and the bouquet. The flowers don't distract attention from the "
                               'handcrafted details. \n'
                               '\n'
                               'Layout: A neat, balanced layout with ample space around the bouquet and ribbon. This '
                               'creates a high-end, handcrafted look, suitable for weddings, bridal gifts, wedding or '
                               'engagement photos, emphasizing softness, elegance, personalization, and love. \n'
                               '\n'
                               'IMPORTANT: The ribbon design must be EXACTLY as in the reference image. Do not change '
                               'anything. Keep the linen material, embroidery style, floral pattern, proportions, and '
                               'overall handcrafted look the same. Do not change the shape of the ribbon or the '
                               'embroidery placement. Only copy the surrounding wedding decorations and delicate '
                               'background. Clearly display the name and date embroidered at both ends of the '
                               'ribbon. \n'
                               '\n'
                               'STYLE: Close-up shots of handcrafted products, soft natural lighting, editorial '
                               'quality, modern minimalist Etsy-style aesthetics, romantic flat layout for weddings, '
                               '1:1 square aspect ratio. \n'
                               '\n'
                               'AVOID: blurry stitching, mechanical appearance, altered embroidery style, distorted '
                               'ribbon shapes, harsh lighting, overexposed highlights, cluttered layout, AI-generated '
                               'noise, text overlays, watermarks. Keep the background simple and elegant, focusing on '
                               'the embroidered ribbon and the delicate wedding setting.'),
                              ('Product display',
                               '2 ribbon song song',
                               'This image showcases handcrafted wedding ribbon products, taken from a reference '
                               'photograph. Two wedding vow books are beautifully displayed on a wooden tray, each '
                               'tied with delicate hand-embroidered ribbon bows. Embroidered names and wedding dates '
                               'are featured on the ribbons at their outermost ends. The ribbons, adorned with '
                               'delicate embroidered floral motifs and personalized inscriptions, gently hold the two '
                               'books together, adding a romantic touch to the composition. Surrounding the books are '
                               'wedding-inspired decorations, including a fresh wedding bouquet in colors matching the '
                               'embroidered flowers on the ribbons, a small wedding ring box with rings inside, and a '
                               'light, flowing veil.\n'
                               '\n'
                               'The composition is warm, refined, and elegant, evoking the romantic atmosphere of a '
                               'wedding. Soft natural light envelops the scene, highlighting the texture of the linen, '
                               'the embroidered ribbons, and the overall craftsmanship. The background remains clean, '
                               'bright, and Spacious and professional, this design showcases vow books and ribbons as '
                               'high-end handcrafted wedding accessories.\n'
                               '\n'
                               'IMPORTANT: The ribbon design is EXACTLY as shown in the reference image. The linen '
                               'material, embroidery style, floral pattern, proportions, and overall handcrafted look '
                               'are preserved. The shape of the ribbon or the embroidery placement remain unchanged. '
                               'Only the surrounding wedding decorations and soft backdrop are reproduced. The names '
                               'and dates embroidered at both ends of the ribbon are clearly visible.\n'
                               '\n'
                               'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                               'elegant decoration, editorial quality, refined Etsy aesthetics, 1:1 square aspect '
                               'ratio.\n'
                               '\n'
                               'AVOID: Ribbon design changes, vow book design changes, harsh studio lighting, '
                               'cluttered backdrops, distracting props, mass-produced look, AI errors, text overlays, '
                               'watermarks.'),
                              ('Product display',
                               'Ribbon đơn — dựng/cuộn',
                               'Product photos of handmade wedding ribbons are taken from reference images. The ribbon '
                               "is elegantly tied into a bow at the back of a bride's hair, showcasing the delicate "
                               'hand-embroidered floral design and personalized text. The ribbon is crafted from soft '
                               "linen fabric with embroidered flowers and a subtle heart symbol between the couple's "
                               'names and wedding date. The bow sits gracefully, adding a romantic touch to the bridal '
                               'hairstyle.\n'
                               '\n'
                               'The background is soft, airy, and minimal, allowing the focus to remain on the '
                               'beautifully embroidered ribbon and the fine details of the design. Soft natural light '
                               'highlights the fabric texture and intricate embroidery, creating a refined and elegant '
                               'atmosphere. The overall scene evokes a feminine, romantic wedding mood suitable for '
                               'premium handmade wedding accessories.\n'
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference photo is retained. '
                               'Maintain the linen texture, embroidery style, floral design, proportions, and overall '
                               'handcrafted look. Do not alter the shape of the ribbon or the placement of the '
                               'embroidery. Only reproduce the surrounding wedding decorations and soft background. '
                               'Clearly show the names and dates embroidery at both ends of the ribbon.\n'
                               '\n'
                               'STYLE: Handmade product photography, romantic bridal styling, soft natural lighting, '
                               'editorial quality, refined Etsy aesthetic, 1:1 square aspect ratio.\n'
                               '\n'
                               'AVOID: changing the ribbon design, changing the embroidery artwork, mass production '
                               'look, harsh studio lighting, cluttered background, distracting props, AI artifacts, '
                               'text overlays, watermarks.'),
                              ('Product display',
                               'Ribbon quanh hoa cô dâu',
                               'This product image of handcrafted wedding ribbons is taken from a reference photo. A '
                               'stunning wedding bouquet, tied with a delicately embroidered ribbon, sits on a soft '
                               'wooden table. The embroidered names and wedding date on the ribbons at the outermost '
                               'ends are clearly visible. The ribbons, adorned with embroidered floral motifs and '
                               'personalized lettering, add a romantic touch to the bouquet. Surrounding the bouquet '
                               'are delicate wedding-inspired details such as a classic pearl jewelry box, a perfume '
                               'bottle, and an elegantly sealed wedding envelope.\n'
                               '\n'
                               'The composition should evoke a sense of sophistication and romance, highlighting the '
                               'exquisite embroidery of the ribbons, the soft material, and the elegant wedding '
                               'decorations. Soft natural light envelops the scene, accentuating the details of the '
                               'ribbons and the bouquet. The backdrop is kept clean and gently blurred, creating an '
                               'elegant, cozy wedding atmosphere that emphasizes the handcrafted quality of the ribbon '
                               "and its connection to the couple's special day.\n"
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference photo must be preserved. '
                               'Maintain the linen fabric, embroidery style, floral design, proportions, and overall '
                               'handcrafted look. Do not change the shape of the ribbon or the placement of the '
                               'embroidery. Only copy the surrounding wedding decorations and the soft backdrop. Keep '
                               'EXACTLY the name and date embroidered at both ends of the ribbon.\n'
                               '\n'
                               'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                               'editorial photo quality, refined Etsy aesthetics, 1:1 square aspect ratio.\n'
                               '\n'
                               'AVOID: ribbon design changes, bouquet shape changes, harsh studio lighting, cluttered '
                               'backdrops, distracting props, AI errors, text overlays, watermarks.'),
                              ('Product display',
                               'Bộ ribbon thêu',
                               'Product photos of handmade wedding ribbons are taken from reference images. A set of '
                               'embroidered wedding ribbons is arranged gracefully on soft satin fabric, featuring '
                               'with personalized text and delicate floral embroidery. The ribbon is carefully placed '
                               'next to a pair of wedding rings, an elegant wedding invitation with a wax seal, and '
                               'soft flower petals, creating a romantic and sophisticated scene. The composition is '
                               'polished and refined, with a soft and clean aesthetic that highlights the beauty of '
                               'the ribbons and the elegance of the surrounding wedding decor. The ribbons are '
                               'slightly curled at the edges, adding texture and depth to the image.\n'
                               '\n'
                               'Soft natural light gently illuminates the scene, bringing out the fine details of the '
                               'embroidery and fabric texture. The background remains clean, bright, and softly '
                               'blurred, evoking an intimate wedding atmosphere suitable for premium handmade '
                               'accessories. \n'
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference photo is retained. '
                               'Maintain the linen texture, embroidery style, floral design, proportions, and overall '
                               'handcrafted look. Do not alter the shape of the ribbon or the placement of the '
                               'embroidery. Only reproduce the surrounding wedding decorations and soft background. '
                               'Clearly show the names and dates embroidery at both ends of the ribbon.\n'
                               '\n'
                               'STYLE: Handmade product photography, romantic wedding styling, soft natural lighting, '
                               'editorial quality, refined Etsy aesthetic, 1:1 square aspect ratio.\n'
                               '\n'
                               'AVOID: changing the ribbon design, changing the floral embroidery, harsh studio '
                               'lighting, cluttered background, distracting props, AI artifacts, text overlays, '
                               'watermarks.'),
                              ('Product display',
                               'Trang trí chai rượu cưới',
                               'This product photo of handcrafted wedding ribbons is taken from a reference image. A '
                               'wedding wine bottle is adorned with an exquisitely hand-embroidered ribbon bow, '
                               'creating a romantic and formal atmosphere. The ribbon, embellished with personalized '
                               'floral embroidery and lettering, is carefully tied around the neck of the bottle. The '
                               'scene includes a champagne glass, a multi-tiered wedding cake, a cake plate, and a '
                               'fresh wedding bouquet in the same color tone as the embroidered flowers on the ribbon, '
                               'elegantly placed nearby, adding to the wedding ambiance.\n'
                               '\n'
                               'Soft natural light envelops the scene, highlighting the delicate details of the '
                               'ribbon, the fabric quality, and the overall craftsmanship. The background remains '
                               'clean and soft, with elements blurred, creating an intimate and elegant wedding '
                               'atmosphere. The ribbon is the main focal point, while the surrounding decorative '
                               'elements add depth and story to the photograph.\n'
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference photo is retained. '
                               'Maintain the linen texture, embroidery style, floral design, proportions, and overall '
                               'handcrafted look. Do not alter the shape of the ribbon or the placement of the '
                               'embroidery. Only reproduce the surrounding wedding decorations and soft background. '
                               'Clearly show the names and dates embroidery at both ends of the ribbon. \n'
                               '\n'
                               'STYLE: Handmade product photography, romantic wedding style, soft natural lighting, '
                               'elegant decorations, editorial photo quality, refined Etsy aesthetics, 1:1 square '
                               'aspect ratio.\n'
                               '\n'
                               'AVOID: Changing ribbon designs, altering embroidery patterns, harsh studio lighting, '
                               'cluttered backgrounds, distracting props, AI errors, text overlays, watermarks.'),
                              ('Product display',
                               'Trong giỏ cưới',
                               'Product photos of handmade wedding ribbons are taken from reference images. A wedding '
                               'basket is elegantly decorated with a hand-embroidered ribbon bow, with personalized '
                               'text and floral embroidery. The ribbon is carefully tied around the handle of the '
                               'basket, which is filled with soft pink rose petals, creating a romantic and whimsical '
                               'atmosphere. The basket is placed on a wooden table, surrounded by soft wedding decor '
                               'elements like delicate flowers, candles, and lace accents, all evoking a refined and '
                               'charming wedding scene.\n'
                               '\n'
                               'Soft natural light gently illuminates the scene, highlighting the embroidered ribbon, '
                               'the soft texture of the linen fabric, and the overall handmade quality. The background '
                               'remains clean and soft, with blurred floral details and wedding table elements, '
                               'ensuring the focus stays on the ribbon and basket. The composition is polished, '
                               'elegant, and perfectly suited for a wedding celebration.\n'
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference photo is retained. '
                               'Maintain the linen texture, embroidery style, floral design, proportions, and overall '
                               'handcrafted look. Do not alter the shape of the ribbon or the placement of the '
                               'embroidery. Only reproduce the surrounding wedding decorations and soft background. '
                               'Clearly show the names and dates embroidery at both ends of the ribbon. \n'
                               '\n'
                               'STYLE: Handmade product photography, romantic wedding styling, soft natural light, '
                               'editorial quality, refined Etsy aesthetic, 1:1 square aspect ratio.\n'
                               '\n'
                               'AVOID: changing the ribbon design, changing the floral embroidery, harsh studio '
                               'lighting, cluttered background, distracting props, AI artifacts, text overlays, '
                               'watermarks.'),
                              ('Lifestyle',
                               'Cô dâu cầm ribbon',
                               'This image of the handcrafted wedding ribbon is taken from a reference photo. In the '
                               'photo, the bride holds a wedding bouquet in the same color tone as the flowers '
                               'embroidered on the ribbon, delicately tied with a hand-embroidered ribbon bow, in an '
                               'outdoor wedding setting. The ribbon is decorated with embroidered floral motifs and '
                               'personalized lettering, the names and date at both ends of the ribbon remain '
                               'unchanged, adding to the charm and romance of the bouquet. The bride smiles radiantly, '
                               'and the scene captures her happy moment with the groom, surrounded by gently falling '
                               'flower petals.\n'
                               '\n'
                               'Soft natural light floods the scene, highlighting the delicate embroidery on the '
                               "ribbon, the fresh lilies in the bouquet, and the bride's elegant wedding dress. The "
                               'background is softened by a gentle green and the romantic outdoor wedding atmosphere, '
                               'focusing on the bride, the bouquet, and the ribbon.\n'
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference photo is retained. '
                               'Maintain the linen material, embroidery style, floral design, proportions, and overall '
                               'handcrafted look. Do not change the shape of the ribbon or the placement of the '
                               'embroidery. Only reproduce the surrounding wedding decorations and the soft '
                               'background. Clearly show the name and date embroidered at both ends of the ribbon.\n'
                               '\n'
                               'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                               'editorial photo quality, refined Etsy aesthetic, 1:1 square aspect ratio.\n'
                               '\n'
                               'AVOID: Changing the ribbon design, altering the shape of the bouquet, harsh studio '
                               'lighting, cluttered background, distracting props, AI errors, text overlays, '
                               'watermarks.'),
                              ('Lifestyle',
                               'Ribbon trên trang phục cô dâu',
                               'This image of the handcrafted wedding ribbon is taken from a reference photo. A '
                               'delicate wedding ribbon, with embroidered floral motifs and personalized lettering, is '
                               'elegantly tied around the wedding bouquet. The bouquet is a beautiful combination of '
                               'fresh flowers in the same color tone as the flowers embroidered on the ribbon, '
                               'creating a soft and romantic look. The ribbon is carefully tied into a bow at the base '
                               'of the bouquet, with personalized lettering clearly visible at both ends. The '
                               'composition captures the image of the bride gently holding the fresh flowers with the '
                               'prominent ribbon draped across her waist, seated on a wooden chair in an outdoor '
                               'wedding setting, evoking a peaceful and romantic wedding moment.\n'
                               '\n'
                               'Soft natural light floods the scene, highlighting the fabric texture and delicate '
                               'embroidery of the ribbon, while also emphasizing the gentle lavender purple and the '
                               'rustic, elegant beauty of the entire wedding decoration. The backdrop is softened by '
                               'light green foliage, creating an intimate atmosphere and focusing on the wedding. The '
                               'overall effect should be romantic, graceful, and sophisticated.\n'
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference image is retained. '
                               'Maintain the linen texture, embroidery style, floral design, proportions, and overall '
                               'handcrafted style. Do not change the shape of the ribbon or the embroidery placement. '
                               'Only reproduce the surrounding wedding decorations and the soft backdrop. Clearly '
                               'display the names and dates embroidered at both ends of the ribbon.\n'
                               '\n'
                               'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                               'edited image quality, refined Etsy aesthetics, 1:1 square aspect ratio.\n'
                               '\n'
                               'AVOID: Changing the ribbon design, altering the floral embroidery pattern, harsh '
                               'studio lighting, cluttered backdrop, distracting props, AI errors, text overlays, '
                               'watermarks.'),
                              ('Lifestyle',
                               'Chú rể với ribbon #1',
                               'The product image for this handmade wedding ribbon is taken from a reference photo. In '
                               'the photo, the bride holds a bouquet of fresh flowers, matching or similar in color to '
                               'the flowers embroidered on the ribbon, tied with soft linen ribbon, the bouquet is '
                               'decorated with embroidered flowers and personalized lettering. The ribbon is tied into '
                               'a delicate bow at the base of the fresh bouquet, matching the color of the embroidered '
                               "flowers on the ribbon, highlighting the couple's names and wedding date (the names and "
                               'date are embroidered at both ends of the ribbon). The bride smiles radiantly, holding '
                               'the bouquet close to her chest, in an outdoor wedding setting, capturing a genuine and '
                               'happy wedding moment.\n'
                               '\n'
                               'The backdrop is a lush, vibrant garden with gently falling colored paper scraps, '
                               'creating a festive and romantic atmosphere. Natural light highlights the delicate '
                               'embroidery on the ribbon and fabric, while the focus remains on the bride, the '
                               'bouquet, and the beautifully tied ribbon. A cozy, cheerful, and romantic setting, '
                               'perfect for showcasing high-end handcrafted wedding accessories.\n'
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference photo is retained. '
                               'Maintain the linen texture, embroidery style, floral design, proportions, and overall '
                               'handcrafted look. Do not change the shape of the ribbon or the placement of the '
                               'embroidery. Only copy the surrounding wedding decorations and the soft material. '
                               'Background. Clearly display the name and date embroidered at both ends of the ribbon.\n'
                               '\n'
                               'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                               'editorial photo quality, refined Etsy aesthetics, 1:1 square aspect ratio.\n'
                               '\n'
                               'AVOID: Changing the ribbon design, altering the floral embroidery, harsh studio '
                               'lighting, cluttered background, distracting props, AI errors, text overlays, '
                               'watermarks.'),
                              ('Lifestyle',
                               'Chú rể với ribbon #2',
                               'The product image for this handmade wedding ribbon is taken from a reference photo. In '
                               'the photo, the bride holds a bouquet of fresh flowers, matching or similar in color to '
                               'the flowers embroidered on the ribbon, tied with soft linen ribbon, decorated with '
                               'embroidered flowers and personalized lettering. The ribbon is tied into a delicate bow '
                               'at the base of the fresh bouquet, matching the color of the embroidered flowers on the '
                               "ribbon, highlighting the couple's names and wedding date (the names and date are "
                               'embroidered at both ends of the ribbon). The bride smiles radiantly, holding the '
                               'bouquet close to her chest, in an outdoor wedding setting, capturing a genuine and '
                               'happy wedding moment.\n'
                               '\n'
                               'The backdrop is a lush, vibrant garden with gently falling colored paper scraps, '
                               'creating a festive and romantic atmosphere. Natural light highlights the delicate '
                               'embroidery on the ribbon and fabric, while the focus remains on the bride, the '
                               'bouquet, and the beautifully tied ribbon. A cozy, cheerful, and romantic setting, '
                               'perfect for showcasing high-end handcrafted wedding accessories.\n'
                               '\n'
                               'IMPORTANT: The EXACT design of the ribbon from the reference photo is retained. '
                               'Maintain the linen texture, embroidery style, floral design, proportions, and overall '
                               'handcrafted look. Do not change the shape of the ribbon or the placement of the '
                               'embroidery. Only copy the surrounding wedding decorations and the soft material. '
                               'Background. Clearly display the name and date embroidered at both ends of the ribbon.\n'
                               '\n'
                               'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                               'editorial photo quality, refined Etsy aesthetics, 1:1 square aspect ratio.\n'
                               '\n'
                               'AVOID: Changing the ribbon design, altering the floral embroidery, harsh studio '
                               'lighting, cluttered background, distracting props, AI errors, text overlays, '
                               'watermarks.'))},
 'wedding_hoop': {'display_name': 'Wedding Hoop',
                  'aliases': ('Wedding Hoop',
                              'wedding hoop',
                              'embroidery hoop wedding',
                              'embroidered hoop',
                              'hoop cưới',
                              'hoop cuoi',
                              'vòng thêu cưới',
                              'vong theu cuoi'),
                  'lock': 'the main product must remain the same circular embroidery hoop with the exact wooden hoop '
                          'frame, stretched fabric, embroidered floral/name layout, stitch colors, hanging/display '
                          'scale, and wedding keepsake identity from the source image',
                  'shots': (('Product display',
                             'Flat display — thêu hoa',
                             'This image of the handcrafted wedding ring is taken from a reference photo. The wedding '
                             'ring is displayed elegantly and flat, highlighting the delicate floral embroidery with '
                             'personalized names and wedding dates. The ring rests gently on a soft white satin '
                             'background, surrounded by romantic wedding-inspired decorative elements such as a '
                             'bouquet of fresh flowers matching the embroidery on the ring stand, wedding invitations, '
                             'and a pair of intertwined wedding rings. The ring is the main focal point, with its '
                             'delicate embroidery clearly and elegantly displayed. \n'
                             '\n'
                             'Soft natural light floods the scene, highlighting the fabric texture, embroidery, and '
                             'craftsmanship of the ring. The clean, soft, and slightly frosted background creates a '
                             'warm and elegant wedding atmosphere. The composition conveys a sense of sophistication, '
                             'romance, and is perfectly suited to showcasing a high-end wedding accessory. \n'
                             '\n'
                             'IMPORTANT: The EXACT design of the wedding ring from the reference photo is retained. '
                             'Maintain the fabric texture, embroidery style, floral design, proportions, and overall '
                             'handcrafted look. Do not alter the shape of the rings or embroidery patterns. Only '
                             'recreate the surrounding wedding decorations and soft background. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                             'editorial photo quality, refined Etsy aesthetics, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: editing wedding photo frame designs, changing embroidery patterns, harsh studio '
                             'lighting, cluttered backgrounds, distracting props, AI errors, text overlays, '
                             'watermarks.'),
                            ('Cận thêu tay',
                             'Cận thêu tay',
                             'Take a close-up photo of the fabric ring ornament from the reference image, focusing on '
                             'the exquisite hand-embroidered details, with clear threads and beautiful stitching. The '
                             'fabric ring frame should be the main focal point, highlighting the embroidery and '
                             'stitching. Soft, natural light from the side will emphasize the depth of the embroidery, '
                             'with a shallow depth of field to create a hazy effect around the fabric. The fabric '
                             'should be neutral and clean-colored, and the handcrafted details must be clearly '
                             'visible, highlighting the quality of the product.\n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the fabric ring ornament from the reference '
                             'image. Preserve the fabric material, embroidery details, thread color, stitching, '
                             'proportions, and handcrafted characteristics. Do not alter the ring ornament in any '
                             'way—only enlarge the existing embroidery details.\n'
                             '\n'
                             'STYLE: Close-up of the handcrafted product, soft natural light, high-quality editing, '
                             'modern minimalist Etsy aesthetic, proportions. Square 1:1.\n'
                             '\n'
                             'AVOID: blurry seams, images that look machine-generated, edited embroidery patterns, '
                             'harsh lighting, overexposed images, highlights, AI errors, text overlaid on images, '
                             'watermarks.'),
                            ('Product display',
                             'Giữa vest chú rể & áo cô dâu',
                             'Product photos of these handcrafted wedding rings are taken from a reference image. A '
                             "wedding ring with delicate embroidery is placed between the groom's suit and the bride's "
                             'wedding dress (the dress gently drapes over the suit), surrounded by elegant wedding '
                             'accessories, soft petals, and a fresh bouquet, all cleverly arranged to create a '
                             'romantic and sophisticated wedding scene. \n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT design of the wedding wreath from the reference image. '
                             'Keep the fabric, embroidery style, proportions, and overall handcrafted look. Do not '
                             'change the design of the wreath or the embroidery. Only recreate the surrounding wedding '
                             'decorations and the soft background environment. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                             'edited image quality, refined Etsy aesthetics, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: Changing the wedding wreath design, editing embroidery details, studio lighting. '
                             'Harsh, distracting background, distracting props, AI errors, text overlays, watermarks.'),
                            ('Lifestyle',
                             'Cô dâu đứng cầm showcase',
                             'This image of a handcrafted wedding ring is taken from a reference photo. The bride is '
                             'standing and holding the exquisitely embroidered wedding ring, showcasing the soft linen '
                             'fabric with hand-embroidered floral motifs (a small ring ornament, only 25 cm). She is '
                             'wearing a romantic, off-the-shoulder wedding dress with natural lace accents. The bride '
                             'is standing in the setting of a beach wedding. \n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT design of the wedding wreath from the reference photo. '
                             'Keep the fabric, embroidery style, floral motifs, proportions, and overall handcrafted '
                             'look. Do not change the wreath design or the embroidered lettering. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, natural wedding style, soft natural lighting, '
                             'edited image quality, refined Etsy aesthetics, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: Changing the wedding wreath design, adjusting embroidery details, overly harsh '
                             'studio lighting, cluttered background, distracting props, AI errors, text overlays." The '
                             'copy is blurry, the image is too dramatic.'),
                            ('Product display',
                             '4 vòng trên voile trắng',
                             'These handcrafted wedding ring product photos are taken from reference images. Four '
                             'wedding rings are elegantly displayed on a soft white voile fabric, adorned with '
                             'delicate embroidered flowers. Each ring is personalized with a DIFFERENT name and date, '
                             'while other embroidery motifs are the same. The rings are arranged symmetrically, each '
                             'clearly displayed to highlight the delicate details of the fabric, embroidery, and '
                             'personalized inscription. \n'
                             '\n'
                             'The surrounding setting includes soft rose petals, fresh flowers, and elegant greenery, '
                             'adding to the romantic and luxurious atmosphere of the wedding. The soft, airy, and '
                             'natural backdrop creates a warm and elegant space. Gentle natural light highlights the '
                             'texture of the fabric and embroidery, emphasizing the exquisite quality and '
                             'craftsmanship of each wedding ring. \n'
                             '\n'
                             'IMPORTANT: The EXACT design of the wedding rings from the reference image is retained. '
                             'Linen fabric texture, style...The embroidery, floral patterns, and proportions are all '
                             'preserved. The overall handcrafted look is retained. The wreath or embroidery design '
                             'remains unchanged. Only the surrounding wedding decorations and the soft background '
                             'environment are recreated. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, romantic wedding style, \n'
                             'Soft natural lighting, editorial photo quality, sophisticated Etsy style. 1:1 square '
                             'aspect ratio. \n'
                             '\n'
                             'AVOID: Changing the wedding photo frame design, changing the embroidery patterns, overly '
                             'harsh studio lighting, cluttered background, distracting props, AI errors, text '
                             'overlays, watermarks.'),
                            ('Gift box',
                             'Gift box',
                             'This image of the handcrafted wedding ring is taken from a reference photo. The ring '
                             'ornament is elegantly displayed inside a soft gift box lined with delicate silk paper. '
                             'The ring, crafted from soft linen with exquisite embroidery, is surrounded by delicate '
                             'wedding ornaments, such as small green leaves, flowers, and elegant ribbons, '
                             'contributing to a romantic and thoughtful appearance. \n'
                             '\n'
                             'The gift box is tilted to highlight the ring ornament, allowing the delicate details of '
                             'the embroidery and fabric to become the focal point. The scene is softly illuminated by '
                             'natural light, highlighting the handcrafted quality of the ring and the thoughtful '
                             'wedding gift atmosphere. The background remains clean, soft, and hazy, evoking a refined '
                             'and intimate mood, perfect for showcasing high-end handcrafted wedding accessories. \n'
                             '\n'
                             'IMPORTANT: The EXACT design of the ring ornament from the reference photo is preserved. '
                             'The fabric, embroidery style, floral design, proportions, and overall handcrafted '
                             'appearance are maintained. Do not change the wreath design or embroidery details. Simply '
                             'recreate the surrounding wedding decorations and a soft backdrop. \n'
                             '\n'
                             'STYLE: Handmade product photography, romantic wedding style, soft natural lighting, \n'
                             'Elegant gift presentation, sophisticated Etsy style, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: Changing the wedding wreath design, altering embroidery details, overly harsh '
                             'studio lighting, cluttered backdrop, distracting props, mass-produced look, AI errors, '
                             'text overlays, watermarks.'),
                            ('Lifestyle',
                             'Tay thêu — process lifestyle',
                             'Lifestyle Product Photo: Handmade Wedding Anniversary Embroidery Frame. A pair of '
                             'delicate hands manipulate the embroidery frame with needle and thread (needle eyelets '
                             'are threaded), while the frame remains the main focus and is clearly displayed (frame '
                             'not shown in the photo). Soft natural light shines from the upper left window, the '
                             'background is gently blurred with warm neutral tones, and the shallow depth of field '
                             'creates a delicate, authentic feel of the handmade product on Etsy. \n'
                             '\n'
                             'IMPORTANT: Keep the EXACT shape of the embroidery frame from the reference photo. Keep '
                             'the wooden frame, fabric, color palette, photo location, embroidery details, and '
                             'proportions. Do not edit the embroidery frame – simply create a new process scene around '
                             'it. \n'
                             '\n'
                             "STYLE: Handmade product photography, soft natural light, editorial quality, Etsy's "
                             'modern minimalist aesthetic, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: altering the product, Unrealistic hand gestures, cluttered workspace, harsh '
                             'lighting, AI errors, text overlays, watermarks.'),
                            ('Lifestyle',
                             'Đôi uyên ương cầm #1',
                             'This product image is a photograph of a handcrafted wedding ring taken from a reference '
                             'photo. The bride and groom are standing next to each other, holding the ring at waist '
                             'level (the ring size is exactly the same as in the reference photo, only 22 cm). The '
                             'bride and groom are wearing wedding attire, and their faces are not visible in the '
                             'photo. The ring is clearly photographed, with the delicate details of the fabric and '
                             'embroidery clearly visible. The couple are standing close together, and the soft '
                             'lighting highlights the ring. \n'
                             '\n'
                             'IMPORTANT: The EXACT design of the wedding ring from the reference photo is preserved. '
                             'The fabric texture, embroidery style, proportions, and overall handcrafted appearance '
                             'are maintained. The ring design or embroidery details are not altered. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                             'edited image quality, refined Etsy aesthetics, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: Changing the wedding photo frame design, altering details... Embroidery details, '
                             'harsh studio lighting, distracting backdrops, distracting props, AI errors, text '
                             'overlays, watermarks.'),
                            ('Product display',
                             '2 vòng tên khác — trên gỗ',
                             'These two product images are taken from a reference photo. Two identical rings with '
                             'different names are displayed on a rustic wooden surface, surrounded by antique books, '
                             'spools of thread, and dried flowers, evoking a fresh, handcrafted, and romantic '
                             'atmosphere. The ring with its delicate embroidery is the focal point of the composition. '
                             'The names and wedding date are clearly embroidered, adding intimacy and sentiment to the '
                             'design. Soft natural light floods the scene, highlighting the fabric texture and the '
                             'exquisite embroidery details. The background includes natural light streaming in from '
                             'the window, creating a gentle, shimmering glow. \n'
                             '\n'
                             'IMPORTANT: The wedding ring design from the reference photo is kept exactly as shown. '
                             'The fabric texture, embroidery style, floral design, proportions, and overall '
                             'handcrafted look are preserved. The design of the ring or the embroidery is not altered. '
                             'Only the surrounding decorations and the soft background environment are reproduced. \n'
                             '\n'
                             'STYLE: Handmade product photography, rustic wedding style, soft natural lighting, edited '
                             'image quality, refined Etsy aesthetics, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: Changing the wedding ring embroidery design, changing the photo frame design, '
                             'using overly harsh studio lighting. Poor lighting, cluttered background, distracting '
                             'props, AI errors, text overlapping images, blurry images.'),
                            ('Product display',
                             'Treo trên móc tường',
                             'This product image of a handmade wedding wreath is taken from a reference photo. An '
                             'elegantly displayed wedding wreath, tied with string and hung on a hook on the wall in '
                             'the wedding space. The wreath, with its delicate embroidery and personalized '
                             'inscription, is the highlight of the composition, adding to the wedding atmosphere. It '
                             'is framed in a wooden hoop with soft linen fabric, carefully crafted to accentuate the '
                             'delicate details of the design. \n'
                             '\n'
                             'IMPORTANT: The wedding wreath design from the reference photo is kept exactly as shown '
                             'in the image. The linen material, embroidery style, floral design, proportions, and '
                             'overall handmade appearance are preserved. The wreath design or embroidery is not '
                             'altered. Only the surrounding wedding decorations and the soft background environment '
                             'are reproduced. \n'
                             '\n'
                             'STYLE: Handmade product photography, romantic wedding style, soft natural lighting, '
                             'edited image quality, refined Etsy aesthetics, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: alterations Wedding frame design, embroidery pattern changes, harsh studio '
                             'lighting, distracting backdrop, distracting props, AI errors, text overlays, '
                             'watermarks.'),
                            ('Product display',
                             'Flat — cận chi tiết thêu #2',
                             'This product photo of a handmade wedding ring is taken from a reference image. The ring '
                             'is displayed elegantly and flat, focusing on the exquisite embroidery technique. The '
                             'ring is placed on a soft linen surface, surrounded by sewing tools such as embroidery '
                             'thread, needles with thread already threaded, a sewing mat, and a small pair of '
                             'scissors. The wedding ring is placed nearby, adding symbolic meaning to the scene. The '
                             'image captures the delicate details of the fabric, the embroidery stitches, and the '
                             'quality of the handmade ring. The background is a handmade work table. \n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT design of the wedding ring from the reference image. '
                             'Preserve the fabric texture, embroidery style, proportions, and overall handmade '
                             'appearance. Do not alter the design of the ring or the embroidery. Only copy the '
                             'surrounding sewing tools and the soft background environment. \n'
                             '\n'
                             'STYLE: Handmade product photography, romantic wedding style, soft natural lighting, '
                             'high-quality editing, refined Etsy aesthetics, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: Changing the wedding embroidery frame design, altering the embroidery artwork, '
                             'harsh studio lighting, cluttered backgrounds, distracting props, AI errors, text '
                             'overlays, watermarks.'),
                            ('Lifestyle',
                             'Đôi uyên ương cầm #2',
                             'This product photo of a handcrafted wedding ring is taken from a reference image. The '
                             'bride and groom are holding their wedding rings in a wedding setting. The ring is the '
                             'main focal point, with personalized names, dates, and a stunning floral design. Soft '
                             'natural light highlights the fabric and embroidery, while surrounding decorations add a '
                             'natural feel to the outdoor setting. \n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT design of the wedding ring. Preserve the fabric texture, '
                             'embroidery style, proportions, and overall handcrafted look. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, romantic wedding style, soft natural light, '
                             'refined Etsy aesthetic, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: altering the wedding ring design, harsh lighting, cluttered background, '
                             'distracting props, AI errors, text overlays, watermarks.'),
                            ('Lifestyle',
                             'Đôi từ phía sau — outdoor',
                             'This product photo of a handcrafted wedding ring was taken from a reference image. The '
                             'bride and groom are photographed from behind in an outdoor wedding setting, both holding '
                             'the ring ornament in their hands and raising it towards the clear blue sky. The couple '
                             'stands close together in elegant wedding attire, creating a romantic and joyful '
                             'atmosphere. The ring ornament is the main focal point of the photo (a small, not overly '
                             'large, ring), while the couple, the open sky, and the distant greenery create an '
                             'emotional love story. \n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the wedding ring from the reference image. Keep '
                             'the material, embroidery style, color palette, proportions, and overall handcrafted '
                             'appearance unchanged. Do not edit the embroidery details. Do not edit the wedding '
                             'ring. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, romantic wedding style, soft natural lighting, '
                             'editorial quality, refined Etsy aesthetics, 1:1 square aspect ratio. \n'
                             '\n'
                             'AVOID: changing the wedding ring design, editing "Correct embroidery details, harsh '
                             'studio lighting, cluttered background, distracting props, AI errors, text overlays, '
                             'watermarks.'),
                            ('Product display',
                             'Kệ nhỏ ngoài trời — reception',
                             'The embroidery frame, photographed from the reference image, is displayed on a small '
                             'shelf on an outdoor reception table at a sunny wedding. The frame is positioned upright '
                             'on a small wooden stand, neatly arranged on the reception table. Surrounding the frame '
                             'are delicate wedding decorations such as linen tablecloths, a few candles, delicate '
                             'dried flowers, and other romantic details in light tones, along with a large wedding '
                             'bouquet that highlights the embroidery on the frame. \n'
                             '\n'
                             'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference image. '
                             'Keep the wooden frame, fabric material, ribbon placement, embroidery details, color '
                             'palette, typography, and proportions the same. Do not alter the embroidery frame – '
                             'simply create a new backdrop and arrange the display around it. \n'
                             '\n'
                             'STYLE: Handcrafted product photography, soft natural lighting, edited image quality, '
                             'modern minimalist Etsy-style aesthetic, elegant wedding decorations, square frame '
                             'proportions. 1:1. \n'
                             '\n'
                             'AVOID: altering product appearance, mass production feel, harsh studio lighting, overly '
                             'cluttered or messy backgrounds, AI errors, text overlays, watermarks.'))},
 'hoops_with_photos': {'display_name': 'Hoops With Photos',
                       'aliases': ('Hoops With Photos',
                                   'hoops with photos',
                                   'photo hoop',
                                   'baby photo hoop',
                                   'embroidery hoop photo',
                                   'khung thêu ảnh',
                                   'khung theu anh',
                                   'vòng thêu ảnh',
                                   'vong theu anh'),
                       'lock': 'the main product must remain the same baby/nursery embroidery hoop or frame with '
                               'photo/name/date elements exactly as in the source image, preserving hoop/frame shape, '
                               'photo placement, stitched name/date layout, fabric texture, and keepsake wall decor '
                               'scale',
                       'shots': (('Product display',
                                  'Kệ gỗ nursery — 2 khung',
                                  'The product image showcases a personalized embroidery frame with a baby theme, as '
                                  'shown in the reference photo. Two picture frames with two different names and two '
                                  'different photos are placed upright against a stack of books on a light-colored '
                                  'wooden shelf, surrounded by soft baby items such as stuffed animals, a small stack '
                                  "of children's books, and a ceramic vase with delicate dried flowers. Soft natural "
                                  'light streams in from the window above and to the left, the background is a '
                                  'minimalist, slightly dark baby room with bright white tones, the items are placed '
                                  'in the center with ample space, and the shallow depth of field creates a gentle '
                                  'bokeh effect. A standout product image for Etsy.\n'
                                  '\n'
                                  'IMPORTANT: Keep the EXACT shape of the embroidery frame from the reference photo. '
                                  'Keep the wooden frame, fabric, color palette, embroidery thread colors, photo '
                                  'placement, embroidery details, and proportions. Do not modify the embroidery frame '
                                  '– only create a new background and style around it. photorealistic, natural '
                                  'lighting, linen texture visible, high detail, product photography style\n'
                                  '\n'
                                  'STYLE: Handcrafted product photography, soft natural lighting, high-quality '
                                  'editing, minimalist modern Etsy aesthetic, 1:1 square aspect ratio.\n'
                                  '\n'
                                  'AVOID: altering product appearance, mass production feel, overly harsh studio '
                                  'lighting, cluttered backgrounds, visually distracting images, AI errors, text '
                                  'overlays, watermarks.'),
                                 ('Lifestyle',
                                  'Trong cũi gỗ — buổi sáng',
                                  'Lifestyle photography: the embroidery frame from the reference image sits in a '
                                  'white wooden cradle, surrounded by small teddy bears, soft morning light filtering '
                                  'through thin white curtains creating gentle accents, a cozy Scandinavian-style '
                                  "children's room, shallow depth of field with the embroidery frame in sharp focus.\n"
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'image. Keep the fabric, color palette, facial features, embroidery details, and '
                                  'proportions. Do not edit the embroidery frame – only create a new scene around it. '
                                  'photorealistic, natural lighting, linen texture visible, high detail, product '
                                  'photography style\n'
                                  '\n'
                                  'STYLE: Handmade product photography, soft natural light, editorial quality, modern '
                                  'minimalist Etsy style, 1:1 square aspect ratio. AVOID: mass production look, harsh '
                                  'studio lighting, cluttered background, AI errors, text overlays, watermarks.'),
                                 ('Flat lay',
                                  'Flat lay — chăn kem + decor bé',
                                  'The product image features a personalized, birthday-themed embroidery frame '
                                  'arranged in a flat layout on a soft, cream-colored baby blanket. The scene is '
                                  'decorated with a few baby mementos such as hats, tiny socks, muslin scarves, and '
                                  'baby toys in various pastel tones. Soft natural light shines from the window above '
                                  'and to the left, the background is clean, airy, and subtly blurred where necessary, '
                                  'the embroidery frame is centrally placed with ample space, and the image conveys a '
                                  'soft, peaceful, handcrafted feel. A standout product photo for Etsy.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'image. Keep the wooden frame, fabric texture, color palette, photo placement, '
                                  'embroidery details, and proportions. Do not edit the embroidery frame – only create '
                                  'a new flat background and surrounding props. photorealistic, natural lighting, '
                                  'linen texture visible, high detail, product photography style\n'
                                  '\n'
                                  'STYLE: Handcrafted product photography, soft natural lighting, editorial quality, '
                                  "aesthetics. Etsy's modern minimalist style, 1:1 square aspect ratio.\n"
                                  '\n'
                                  'AVOID: product alterations, harsh shadows, heavy props, clutter, highly distracting '
                                  'colors, AI errors, text overlays, watermarks.'),
                                 ('Product display',
                                  'Treo tường nursery',
                                  "The product image shows a personalized commemorative embroidery frame for a baby's "
                                  'birthday, displayed as a wall decoration in a nursery with soft, neutral tones. The '
                                  'frame is tied with string and hung on a nail on a white wall above a light-colored '
                                  'wooden shelf, below which are delicate decorations such as teddy bears, small '
                                  'books, and dried flowers. Strong natural light shines from the window above and to '
                                  'the left, the minimalist and slightly soft background highlights the embroidery '
                                  'frame, and the shallow depth of field creates a gentle bokeh effect. A standout '
                                  'handcrafted product image for Etsy. \n'
                                  '\n'
                                  'IMPORTANT: Keep the EXACT shape of the embroidery frame from the reference image. '
                                  'Keep the wooden frame, fabric, color palette, image placement, embroidery details, '
                                  'and proportions the same. Do not modify the embroidery frame – simply create a new '
                                  'environment around it. \n'
                                  '\n'
                                  'STYLE: Handcrafted product photography, soft natural lighting, high-quality '
                                  'editing, modern minimalist Etsy aesthetic, 1:1 square aspect ratio. \n'
                                  '\n'
                                  'AVOID: Product alterations, dark walls, harsh lighting, excessive wall decorations, '
                                  'clutter, AI errors, text overlays, watermarks.'),
                                 ('Lifestyle',
                                  'Mẹ cầm khung — linen dress',
                                  'The product photo features a personalized, gently held, commemorative embroidery '
                                  "frame for a baby's birthday, held by a woman in a white or beige linen dress. The "
                                  "woman's face is not visible in the shot. Soft, natural light streams in from a "
                                  'window in the upper left, the background is a warm, minimalist cream-colored '
                                  'interior with a subtle blurring effect, and the shallow depth of field creates a '
                                  'soft, emotionally rich atmosphere in the Etsy style. A standout lifestyle product '
                                  'photo.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'photo. Keep the wooden frame, fabric, color palette, photo placement, embroidery '
                                  'details, and proportions. Do not edit the embroidery frame – simply create a new '
                                  'lifestyle context around it. photorealistic, natural lighting, linen texture '
                                  'visible, high detail, product photography style\n'
                                  '\n'
                                  'STYLE: Handmade product photography, soft natural light, editorial quality, modern '
                                  'minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                                  '\n'
                                  "AVOID: altering the product's appearance, displaying distracting facial details, "
                                  'awkward or cluttered poses, AI errors, text overlays, and watermarks.'),
                                 ('Cận thêu tay',
                                  'Macro — thêu tên + ngày',
                                  'Take a close-up photo of the embroidery frame from the reference image, focusing on '
                                  'the exquisite hand-embroidery details, with clear threads and beautiful stitching. '
                                  'The fabric embroidery frame should be the main focal point, highlighting the '
                                  'embroidery and stitching. Soft, natural light from the side will emphasize the '
                                  'depth of the embroidery, with a shallow depth of field to create a hazy effect '
                                  'around the fabric. The fabric should be neutral and clean-colored, and the '
                                  'handcrafted details must be clearly visible, highlighting the quality of the '
                                  'product. \n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the fabric embroidery frame from the '
                                  'reference image. Preserve the fabric material, embroidery details, thread color, '
                                  'stitching, proportions, and handcrafted characteristics. Do not alter the '
                                  'embroidery frame in any way—only enlarge the existing embroidery details. \n'
                                  '\n'
                                  'STYLE: Close-up of the handcrafted product, soft natural light, high-quality '
                                  'editing, modern minimalist Etsy-style aesthetic, square aspect ratio.1:1. \n'
                                  '\n'
                                  'AVOID: blurry seams, images that look machine-generated, altered embroidery '
                                  'patterns, harsh lighting, overexposed images, highlights, AI errors, text overlaid '
                                  'on images, watermarks.'),
                                 ('Product display',
                                  'Trên giỏ mây + decor bé',
                                  "The product image is a personalized commemorative embroidery frame for a baby's "
                                  'birthday, placed on a ONE-PIECE WICKER BASKET. INSIDE THE BASKET, THERE ARE '
                                  'ADDITIONAL BABY TOYS DECORATED ON AN OUTDOOR TABLE. The soft, bright, balanced, and '
                                  'focused natural light, with a shallow depth of field, creates a tranquil, '
                                  'Etsy-style atmosphere.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'image. Keep the wooden frame, fabric material, color palette, image placement, '
                                  'embroidery details, and proportions. Do not edit the embroidery frame – simply '
                                  'create a new background around it. photorealistic, natural lighting, linen texture '
                                  'visible, high detail, product photography style\n'
                                  '\n'
                                  'STYLE: Handmade product photography, soft natural light, editorial quality, modern '
                                  'minimalist Etsy-style aesthetic, 1:1 square aspect ratio.\n'
                                  '\n'
                                  'AVOID: Editing the product. Products, props with strong colors, overly elaborate '
                                  'backdrops, stiff studio appearance, AI errors, text overlays, watermarks.'),
                                 ('Gift box',
                                  'Gift box — quà tặng bé',
                                  'The product image is a personalized, beautifully presented commemorative embroidery '
                                  "frame for a baby's birthday, housed in an open gift box. The box is lined with soft "
                                  'silk paper and decorated with satin ribbon, delicate dried flowers in neutral '
                                  'pastel tones. Soft natural light streams in from the upper left window, the '
                                  'background is minimalist and slightly muted with white tones, and the embroidery '
                                  'frame remains the main focal point. A stunning Etsy product photo, ready to be '
                                  'given as a gift.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'image. Keep the wooden frame, fabric, color palette, photo placement, embroidery '
                                  'details, and proportions. Do not edit the embroidery frame – simply create a new '
                                  'gift frame around it.\n'
                                  '\n'
                                  'STYLE: Handmade product photography, soft natural lighting, editorial quality, '
                                  "Etsy's modern minimalist aesthetic, 1:1 square aspect ratio.\n"
                                  '\n'
                                  'AVOID: product changes, flashy gift packaging, bold colors, clutter, harsh '
                                  'lighting, AI errors, text overlays, watermarks.'),
                                 ('Quy trình',
                                  'Process — tay thêu',
                                  'Product Photo in Lifestyle Style: A personalized birthday commemorative embroidery '
                                  'frame showcasing the hand-embroidery process. A pair of hands gently manipulate the '
                                  'embroidery frame with needle and thread (thread threaded through the needle eye), '
                                  'while the frame remains the main focus and is clearly displayed (the frame is not '
                                  'shown in the photo). Soft natural light shines from the upper left window, the '
                                  'background is gently blurred with warm neutral tones, and the shallow depth of '
                                  'field creates a delicate, authentic feel of the handcrafted product on Etsy.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'photo. Keep the wooden frame, fabric, color palette, photo placement, embroidery '
                                  'details, and proportions. Do not edit the embroidery frame – simply create a new '
                                  'process scene around it. photorealistic, natural lighting, linen texture visible, '
                                  'high detail, product photography style\n'
                                  '\n'
                                  'STYLE: Handcrafted product photography, soft natural light, editorial quality, '
                                  "Etsy's modern minimalist aesthetic, 1:1 square aspect ratio.\n"
                                  '\n'
                                  'AVOID: product changes, unrealistic hand positions, cluttered workspace, harsh '
                                  'lighting, AI errors, text overlays, watermarks.'),
                                 ('Product display',
                                  '3 khung grouped — tên khác',
                                  'The product image shows three personalized commemorative embroidery frames with the '
                                  "baby's name and birth date, displayed together as a unified commemorative "
                                  'collection. Each frame features a different baby photo and a different English '
                                  'name, but retains the same handcrafted style, soft fabric, wooden frame, delicate '
                                  'embroidery details, and personalized birthday celebration layout. The three frames '
                                  'are placed LAYING on a clean, light-colored oak table, slightly overlapping '
                                  'naturally. Decorate the scene with a few soft items for the nursery such as stuffed '
                                  'animals, small baby shoes, muslin cloths, and delicate dried flowers.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT handcrafted shape and appearance of the embroidery '
                                  'frames from the reference image. Keep the wooden frame, linen fabric, color '
                                  'palette, photo placement, embroidery details and proportions, and thread colors for '
                                  'each detail. Each frame should have its own unique touch by using a different baby '
                                  'photo and a different English name. Do not edit or distort the embroidery frame '
                                  'style – simply create a new background and arrange three personalized versions '
                                  'side-by-side.\n'
                                  '\n'
                                  'STYLE: Handmade product photography, soft natural lighting, editorial quality, '
                                  "modern minimalist Etsy style. Warm, aesthetically pleasing children's room decor, "
                                  '1:1 square aspect ratio.\n'
                                  '\n'
                                  'AVOID: altering product styles, making all names or photos look identical, '
                                  'mass-produced look, harsh studio lighting, overly cluttered backgrounds, AI errors, '
                                  'illegible personalization, text overlays, watermarks.'),
                                 ('Lifestyle',
                                  'Bé chạm tay vào khung',
                                  "The product image is a personalized commemorative embroidery frame for a baby's "
                                  'birthday, featuring a baby gently holding or touching the embroidery frame in a '
                                  'natural, tranquil scene. The baby, dressed in a pastel-toned bib, is seated on a '
                                  'sofa in the living room, with the embroidery frame clearly displayed as the main '
                                  "focal point. The baby's hands gently and naturally hold the frame, creating a "
                                  'heartwarming commemorative gift. Soft natural light shines from the window above '
                                  'and to the left, centering the composition.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'image. Keep the wooden frame, fabric, color palette, photo placement, embroidery '
                                  'details, and proportions unchanged. Do not alter the embroidery frame – simply '
                                  'create a new background and a new scene around it. The baby should interact '
                                  'naturally with the embroidery frame, but the product must be fully and unchanged. '
                                  'photorealistic, natural lighting, linen texture visible, high detail, product '
                                  'photography style\n'
                                  '\n'
                                  'STYLE: Handcrafted product photography, soft natural lighting, edited image '
                                  "quality, modern minimalist Etsy aesthetic, warm children's room decor style, 1:1 "
                                  'square aspect ratio.\n'
                                  '\n'
                                  'AVOID: altering product appearance, unrealistic baby poses, obscuring too much of '
                                  'the frame, harsh studio lighting, cluttered background, mass production feel, AI '
                                  'errors, text overlays, watermarks.'),
                                 ('Lifestyle',
                                  'Mẹ bế bé — bé ôm khung',
                                  "The product image is a personalized commemorative embroidery frame for a baby's "
                                  'birthday, featuring a mother holding her child, with the baby gently hugging or '
                                  'touching the frame. The mother is wearing a white lace dress, her face not visible. '
                                  'The baby is wearing a simple bib in neutral and natural tones, gently hugging the '
                                  'frame, creating a tender and memorable moment. The frame is clearly positioned in '
                                  'the center, with the mother and baby naturally surrounding it.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'image. Keep the wooden frame, fabric, color palette, photo placement, embroidery '
                                  'details, and proportions the same. Do not alter the frame – simply create a new '
                                  'background and a vibrant setting around it. Mother and baby should interact '
                                  'naturally with the frame, but the product must be fully displayed, unchanged, and '
                                  'easily recognizable. photorealistic, natural lighting, linen texture visible, high '
                                  'detail, product photography style\n'
                                  '\n'
                                  'STYLE: Handcrafted product photography, soft natural lighting, high-quality '
                                  "editing, modern minimalist Etsy-style aesthetics, warm children's room decor, 1:1 "
                                  'square aspect ratio.\n'
                                  '\n'
                                  'AVOID: altering product appearance, unrealistic mother or child poses, obscuring '
                                  'too much embroidery, harsh studio lighting, cluttered backgrounds, mass production '
                                  'feel, AI errors, text overlays, watermarks.'),
                                 ('Product display',
                                  'Kệ bàn tiệc sinh nhật bé',
                                  'Product photos of the embroidery frame, taken from a reference image, are displayed '
                                  'on a small shelf placed on a birthday party table. The embroidery frame stands '
                                  'upright on a small, elegant wooden or light-colored stand, neatly placed on the '
                                  'birthday table as a centerpiece. Surrounding the scene are delicate birthday '
                                  'decorations such as a tablecloth with pastel-colored balloons in the background, a '
                                  'few wrapped gift boxes, delicate flowers, small candles, and subtle party details '
                                  'in soft neutral and pastel tones.\n'
                                  '\n'
                                  'IMPORTANT: Maintain the EXACT shape of the embroidery frame from the reference '
                                  'image. Keep the wooden frame, fabric material, photo location, embroidery details, '
                                  'color palette, typography, and proportions the same. Do not edit the embroidery '
                                  'frame – only create a new background and set up the display around it. '
                                  'photorealistic, natural lighting, linen texture visible, high detail, product '
                                  'photography style\n'
                                  '\n'
                                  'STYLE: Handcrafted product photography, soft natural lighting, high-quality '
                                  "editing, Etsy's modern minimalist aesthetic, elegant birthday party decorations, "
                                  '1:1 square aspect ratio.\n'
                                  '\n'
                                  'AVOID: altering product appearance, mass production feel, harsh studio lighting, '
                                  'overly cluttered or messy backgrounds, AI errors, text overlays, watermarks.'))},
 'dress_baby': {'display_name': 'Dress Baby',
                'aliases': ('Dress Baby',
                            'baby dress',
                            'toddler dress',
                            'kids dress',
                            'children dress',
                            'child dress',
                            "child's dress",
                            "children's dress",
                            'girls dress',
                            'girl dress',
                            'linen dress',
                            'white linen dress',
                            'sleeveless dress',
                            'ruffled dress',
                            'ruffle sleeve dress',
                            'flutter sleeve dress',
                            'pinafore dress',
                            'embroidered dress',
                            'váy bé',
                            'vay be',
                            'váy em bé',
                            'vay em be'),
                'lock': 'the main product must remain the same baby/child dress with the exact dress silhouette, '
                        'sleeves/ruffles/ties/hem, fabric color, embroidery placement, garment scale, and construction '
                        'from the source image',
                'shots': (('Product display',
                           '4 con manocanh',
                           'The product photos feature four dresses in different colors, based on the provided '
                           'reference image. The four dresses are displayed on mannequins standing side-by-side, '
                           'arranged in two rows. Each dress has a soft color. Gentle natural light shines from the '
                           'window above and to the left, creating a shimmering effect on the dresses. The background '
                           'is minimalist, white, and the objects are centrally positioned with ample space between '
                           'them. The shallow depth of field creates a soft bokeh effect. \n'
                           '\n'
                           'IMPORTANT: Maintain the EXACT shape, proportions, and color palette of the dresses as in '
                           'the reference image. Preserve the fabric texture, embroidery details, and proportions. Do '
                           'not edit or alter the dresses themselves – only create a new background around them. \n'
                           '\n'
                           'STYLE: Handcrafted product photography, soft natural lighting, editorial quality, modern '
                           'minimalist Etsy-style aesthetic, 1:1 square aspect ratio. \n'
                           '\n'
                           "AVOID: altering the dress's appearance or the product's form. Mass production. Consecutive "
                           'shots, harsh studio lighting, cluttered backgrounds, distracting props, distorted '
                           'embroidery, spelling errors, missing names, AI-generated errors, overlapping text, blurry '
                           'images.'),
                          ('Product display',
                           '3 chiếc trên bàn',
                           'Product photos of three dresses in three different colors are based on the provided '
                           'reference image. The three dresses are placed side-by-side on a white table, stacked '
                           'lightly to form a triangle, decorated with small flowers and a few playful props, '
                           "including children's shoes. Each dress is a soft pastel color. Gentle natural light shines "
                           'from above and from the left, highlighting the dresses and creating an inviting scene. The '
                           'minimalist background features a rough wooden tabletop, and the items are arranged with '
                           'ample spacing to create balance. The shallow depth of field creates a soft bokeh effect, '
                           'highlighting the dresses. The photo was taken directly from above, focusing on the '
                           'dresses.\n'
                           '\n'
                           'IMPORTANT: Maintain the EXACT shape, proportions, and color palette of the dresses as in '
                           'the reference image. Preserve the fabric texture, embroidery details, and proportions. Do '
                           'not edit or alter the dresses themselves – only create a new background around them. '
                           'them.\n'
                           '\n'
                           'STYLE: Handmade product photography, soft natural lighting, editorial quality, minimalist '
                           "modern Etsy aesthetic, warm and rustic style inspired by children's rooms, 1:1 square "
                           'aspect ratio.\n'
                           '\n'
                           "AVOID: Altering the dress's appearance, mass-produced look, harsh studio lighting, "
                           'cluttered background, distracting props, distorted embroidery, missing name, AI-generated '
                           'errors, overlapping text, blurry images.'),
                          ('Product display',
                           '2 váy',
                           "The product image shows two children's dresses based on the provided reference image. Two "
                           'dresses, in different colors but the same pattern, are laid flat on a wooden table, '
                           'photographed from a straight, top-down perspective. Surrounding the dresses are several '
                           "fresh fruits, green leaves, small decorative flowers, and some children's room-style "
                           "decorative items placed naturally around the layout. A pair of children's shoes is added "
                           'near the bottom right corner. The layout is balanced, airy, and visually pleasing, with '
                           'the dresses as the main focal point.\n'
                           '\n'
                           'IMPORTANT: Maintain EXACTLY the shape, proportions, neckline, sleeve style, bow placement, '
                           'fabric, embroidery placement, and overall style of the dresses from the reference image. '
                           'Maintain the overall embroidery style and original design; do not redraw or over-detail '
                           'the embroidery details, so that the pattern can be reused for other embroidered dresses. '
                           'Design. Do not alter the dress itself. Recreate only the background, surrounding '
                           'accessories, and overall composition.\n'
                           '\n'
                           'STYLE: Handmade product photography, soft natural lighting, editorial quality, warm and '
                           'charming Etsy style, clean silhouettes, gentle shadows, realistic fabric details, flat '
                           'top-down composition, 1:1 square aspect ratio.\n'
                           '\n'
                           'AVOID: altering dress designs, changing embroidery styles, mass-produced look, harsh '
                           'studio lighting, cluttered styling, distracting accessories, distorted garment shapes, AI '
                           'errors, text overlays, watermarks, or unrealistic colors.'),
                          ('Product display',
                           'manocanh 2 mặt',
                           'Use the dress in the reference image as the main product. Create a neat, Etsy-style '
                           "product photo, displaying two dresses on a child's mannequin, one in the front and one in "
                           'the back (with two small wooden buttons evenly spaced at the back). Place the dress in an '
                           'outdoor garden setting with soft, natural flowers and greenery in the background. Ensure '
                           'the dress retains its shape, color, texture, and details as in the reference image. Do not '
                           'edit, redesign, or alter the dress itself.\n'
                           '\n'
                           'IMPORTANT: Maintain the exact shape, proportions, and color palette of the dress as in the '
                           'reference image. Preserve the fabric texture, embroidery details, and proportions. Do not '
                           'edit or alter the dress itself – only create a new background around it.\n'
                           '\n'
                           'STYLE: Handcrafted product photography, soft natural lighting, professional quality, '
                           'modern minimalist Etsy aesthetic, realistic product photos, 1:1 square aspect ratio.\n'
                           '\n'
                           'AVOID: altering clothing styles, mass-produced looks, harsh studio lighting, cluttered '
                           'props, text overlays, logos, watermarks, and AI-generated errors.'),
                          ('Gift box',
                           'hộp quà',
                           'Use the dress in the reference photo as the main product. Display the dress neatly in a '
                           'paper gift box. Place the gift box containing the dress in a bright, airy, minimalist '
                           'space with natural decorations such as dried flowers, eucalyptus leaves, and small, '
                           'neutral ornaments. \n'
                           '\n'
                           'Soft natural light should shine from above and slightly to the left. The background should '
                           'be slightly blurred to create a subtle bokeh effect. Place the product in the center with '
                           'ample space. Shoot from above, focusing on the dress in the gift box. The final image '
                           'should convey a natural, high-end, and professional feel, suitable for making a strong '
                           'impression on Etsy. \n'
                           '\n'
                           "STYLE: Handmade product photography, soft natural lighting, high-quality editing, Etsy's "
                           'modern minimalist aesthetic, realistic product photography, 1:1 square aspect ratio. \n'
                           '\n'
                           'AVOID: product appearance editing, mass-produced look, harsh studio lighting, cluttered '
                           'decorations, overlays. The original, logo, watermark, and AI details.'),
                          ('Product display',
                           '',
                           'Use the two dresses in the reference photos, in two different colors, as the main '
                           'products. Display the dresses neatly, hanging two dresses of different colors on wooden '
                           'hangers on a clothesline. Place the dresses in a bright, airy, minimalist space with '
                           'natural items such as dried flowers, eucalyptus leaves, and small neutral-colored '
                           'decorative items. Maintain the original shape, material, color, and details of the '
                           'dresses. Do not alter, redesign, or add embroidery or patterns. \n'
                           '\n'
                           'Soft natural light should shine from above and slightly to the left. The background should '
                           'be slightly blurred to create a subtle bokeh effect. Place the products in the center with '
                           'ample space. \n'
                           '\n'
                           'IMPORTANT: Maintain the EXACT shape, material, color, and details of each dress. Do not '
                           'modify, repaint, distort, or redesign the dresses. Only create a background and style '
                           'around them. \n'
                           '\n'
                           'STYLE: Handcrafted product photography, soft natural light, high-quality editing, '
                           'minimalist aesthetic. Etsy-style photos, realistic product images, 1:1 square aspect '
                           'ratio. \n'
                           '\n'
                           'AVOID: altered product appearance, mass-produced look, harsh studio lighting, cluttered '
                           'objects, text, overlays, logos, watermarks, AI-generated image noise.'),
                          ('Lifestyle',
                           'em bé công viên',
                           'Use the dress in the reference photo as the main product. Photograph the baby wearing that '
                           'dress sitting and playing with friends on a picnic mat in an outdoor park setting, '
                           'capturing natural, authentic moments like walking or running. Use soft, natural light from '
                           'above, slightly tilted to the left. The background should be slightly blurred to create a '
                           'subtle bokeh effect, focusing on the baby and the dress, while keeping the scene bright, '
                           'airy, and minimalist. Place the subject in the center with ample space. \n'
                           '\n'
                           'IMPORTANT: Maintain the EXACT shape, material, color, and details of the dress. Do not '
                           'edit, redraw, distort, or redesign the dress. Only create the background and style around '
                           'the baby wearing it. \n'
                           '\n'
                           'STYLE: Handmade product photography, soft natural light, professional image quality, '
                           'modern minimalist aesthetic in the Etsy style, authentic product photography, square '
                           'aspect ratio. 1:1. \n'
                           '\n'
                           'AVOID: image editing. Product appearance, mass production look, harsh studio lighting, '
                           'cluttered props, text overlays, logos, watermarks, and AI-generated image noise.'),
                          ('Lifestyle',
                           'sofa',
                           'Use the dress in the reference photo as the main product. Dress the child in the dress, '
                           'have them sit on a neutral-colored sofa playing games or eating fruit, and capture their '
                           'natural, authentic expressions and poses. Keep the dress exactly as it is in shape, '
                           'material, color, and details. Do not edit, redesign, add embroidery, or patterns. Use '
                           'soft, natural light from a window on one side. The background should be slightly blurred '
                           'to create a subtle bokeh effect, keeping the scene bright, airy, and minimalist. Place the '
                           'subject in the center with ample space. \n'
                           '\n'
                           'IMPORTANT: Keep the EXACT shape, material, color, and details of the dress. Do not edit, '
                           'redraw, distort, or redesign the dress. Only create a background and style around the '
                           'child wearing the dress. \n'
                           '\n'
                           'STYLE: Handmade product photography, soft natural light, professional image quality, '
                           'modern minimalist aesthetic in the Etsy style, product photography. Authentic product, 1:1 '
                           'square aspect ratio. \n'
                           '\n'
                           'AVOID: altering product appearance, mass production look, harsh studio lighting, cluttered '
                           'props, text overlays, logos, watermarks, and AI-generated image noise.'),
                          ('Lifestyle',
                           'em bé',
                           'Use the dresses in the reference photos as the main product. Photograph the children '
                           'wearing the dresses against a white background: one child facing forward, one child facing '
                           'backward (the back of the dress has two small wooden buttons spaced evenly apart). Add the '
                           "following text to the photo: 'This lovely cotton linen children's dress is meticulously "
                           'handcrafted by skilled artisans from a traditional Vietnamese embroidery village. Each '
                           "dress is a work of art made with love, and we hope you love it as much as we do!' - Ensure "
                           'the image is legible, logical, and visually appealing. Maintain the original shape, '
                           'material, color, and details of each dress. Do not alter, redesign, embroider, or add any '
                           'decorative details. \n'
                           '\n'
                           'IMPORTANT: Maintain EXACTLY the shape, material, color, and details of each dress. Do not '
                           'alter, redraw, distort, or redesign the dress. Create only a background and styling around '
                           'the babies in dresses. \n'
                           '\n'
                           'STYLE: Handmade product photography, soft natural lighting, professional image quality, '
                           'modern minimalist aesthetics in the Etsy style, realistic product photography, 1:1 square '
                           'aspect ratio. \n'
                           '\n'
                           'AVOID: altering product appearance, mass production look, harsh studio lighting, cluttered '
                           'props, text overlays, logos, watermarks, and AI-generated image noise.'),
                          ('Cận thêu tay',
                           'thêu tay',
                           'Take a realistic, close-up photo of the embroidery on the dress, similar to the embroidery '
                           'pattern on the dress in the reference photo. The close-up should clearly show the '
                           'hand-embroidered details. The photo should only show the embroidery, not the entire '
                           'dress. \n'
                           '\n'
                           'Soft natural light from the window above and to the left creates gentle shadows and '
                           'highlights the texture of the linen fabric, the stitches, the thread details, and the '
                           'handcrafted process. Use a shallow depth of field with a slightly blurred background. The '
                           'focus should be on the hands, needle, embroidery frame, linen fabric, and the '
                           'hand-embroidery process. \n'
                           '\n'
                           'STYLE: Photographing the hand-embroidery process, soft natural light from the window, '
                           'realistic product photography, editorial quality, modern minimalist aesthetics in the Etsy '
                           'style, rustic workspace, natural linen fabric, 1:1 square aspect ratio. \n'
                           '\n'
                           'AVOID: Harsh studio lighting, cluttered background, plastic-looking fabric, mass-produced '
                           'appearance, smudged hands, distorted fingers. Misaligned stitches, incorrect needle '
                           'placement, unrealistic embroidery lines, AI errors, text overlays, logos, watermarks.'),
                          ('Quy trình',
                           'quy trình',
                           "Create a realistic mosaic of the crafting process for a children's embroidered dress, "
                           'inspired by the reference image. The final image should showcase the entire crafting '
                           'process in seven clear frames, arranged like a high-end product workflow chart on Etsy, '
                           'with soft rounded corners, natural lighting, and a clean workshop space. \n'
                           '\n'
                           'Frame 1: A woman carefully selecting linen or cotton-linen blend fabric in the exact same '
                           'color as the dress in the reference image. Show the fabric pieces neatly folded on a '
                           'wooden table or shelf, with spools of thread, dried flowers, and simple sewing tools '
                           'nearby. \n'
                           '\n'
                           'Frame 2: Close-up of a craftsman sketching the overall embroidery layout onto the fabric '
                           "using tailor's chalk. The details of the embroidery should accurately match the dress in "
                           'the reference image. \n'
                           '\n'
                           'Frame 3: Close-up of hands hand-embroidering the sketched design onto the fabric inside a '
                           'wooden embroidery frame. Figure 4: Showing the needle, thread, linen fabric, and '
                           'meticulous hand-stitching, accurately reflecting the design in the reference image. \n'
                           '\n'
                           'Figure 5: A seamstress cuts the fabric into separate parts of the dress on a rustic wooden '
                           'table. Showing scissors, pattern pieces, sleeves, bodice, skirt pieces, and soft linen '
                           'fabric. Maintaining consistent fabric colors with the reference product image. \n'
                           '\n'
                           'Figure 6: A Vietnamese seamstress sews the parts of the dress together using a sewing '
                           "machine, creating a complete children's dress. Showing the craft workshop space with "
                           'natural light, sewing tools, thread, and fabric scraps around the work area. \n'
                           '\n'
                           'Figure 7: The completed dress is being gently ironed on an ironing board or linen-covered '
                           'table. Showing the fabric becoming smooth and neat while retaining its handcrafted texture '
                           'and natural softness. \n'
                           '\n'
                           "Figure 8: The completed children's dress is neatly folded inside a kraft paper gift box, "
                           'placed alongside a matching hair tie. Add a few dried flowers, eucalyptus leaves, a spool '
                           'of thread, and other neutral crafting items around the box. The presentation should feel '
                           'upscale, warm, and ready to be given as a gift to customers on Etsy. \n'
                           '\n'
                           'IMPORTANT: Always choose fabric colors that exactly match the product in the reference '
                           'image. Keep the dress looking handmade, soft, natural, and high-end. The embroidery '
                           'process must look authentic, not mass-produced. Do not alter the dress style to resemble a '
                           'different product. Do not add text overlays, labels, logos, or watermarks. \n'
                           '\n'
                           'STYLE: Photograph the handcrafted embroidery process, photograph the product in an Etsy '
                           'editorial style, bright natural light from a window, a rustic wooden table, a soft '
                           'cream-colored studio background, authentic linen texture, delicate hand stitching, a '
                           'high-end handmade gift presentation, a neat collage layout, and a 1:1 square aspect '
                           'ratio. \n'
                           '\n'
                           'AVOID: Harsh studio lighting, overly yellow lighting, cluttered workspace, plastic-looking '
                           'fabric, machine embroidery appearance, distorted hands, extra fingers, incorrect needle '
                           'placement, inaccurate fabric color, messy dress structure, unrealistic sewing details, AI '
                           'errors, text overlays, logos, watermarks.'))},
 'linen_pillowcase': {'display_name': 'Linen Pillowcase',
                      'aliases': ('Linen Pillowcase',
                                  'linen pillowcase',
                                  'linen pillow',
                                  'embroidered linen pillow',
                                  'vỏ gối linen',
                                  'vo goi linen',
                                  'gối linen',
                                  'goi linen'),
                      'lock': 'the main product must remain the same linen pillowcase/cushion with the exact '
                              'rectangular pillow shape, soft volume, linen weave, embroidered name or motif '
                              'placement, seam/edge finish, fabric color, and home decor scale from the source image',
                      'shots': (('Lifestyle',
                                 'Phụ nữ cầm/ôm gối',
                                 'Use the pillow in the reference image as the main product. Create a realistic '
                                 'product photo depicting everyday life, showing a middle-aged or young woman '
                                 'comfortably seated in a living room (face obscured, only the nose and lower body '
                                 'visible), holding the handcrafted decorative pillow as in the reference image, '
                                 'resting it on her lap. The pillow should be the focal point of the photo, '
                                 'highlighting the fabric, the raised embroidery details, and the high-end finish of '
                                 'the handcrafted product. Soft natural light from a nearby window creates a bright, '
                                 'airy, and natural feel. Use a shallow depth of field to highlight the pillow while '
                                 'maintaining the gentle authenticity of the woman and the living room. \n'
                                 '\n'
                                 'IMPORTANT: Maintain the shape, fabric, color palette, raised embroidery texture, '
                                 'proportions, and handcrafted look of the pillow from the reference image. Do not '
                                 'redesign, redraw, distort, or alter the pillow. Do not add specific embroidery '
                                 'patterns. The embroidery pattern must maintain its overall quality and Versatile for '
                                 'any application. Pillow design. Background only. Landscape and lifestyle surrounding '
                                 'the person holding the pillow. \n'
                                 '\n'
                                 'STYLE: Authentic. Handmade product photos. Lifestyle photos edited in the Etsy '
                                 'style. Home. Beautiful interior spaces, soft natural light from windows, living '
                                 'rooms with neutral tones, shallow depth of field, high-end handmade pillows, raised '
                                 'embroidery, 1:1 square aspect ratio. \n'
                                 '\n'
                                 'AVOID: altering pillow designs, oversized embroidery, embroidering specific '
                                 'characters or names, harsh studio lighting, cluttered backgrounds, plastic-looking '
                                 'fabrics, flat machine embroidery, distorted hands, added fingers, blurry pillow '
                                 'details, mass-produced look, AI errors, text overlays, logos, watermarks.'),
                                ('Product display',
                                 'Hero — 1 gối trên giường',
                                 'Use the pillow in the reference image as the main product. Create an authentic '
                                 'Etsy-style product photo showcasing the handcrafted decorative pillow neatly placed '
                                 'on a cozy bed in a bright, neutral bedroom. The pillow should be the centerpiece, '
                                 'complemented by soft white bedding, neutral linen pillows, a light-colored '
                                 'headboard, a bedside lamp, small potted plants, and minimalist home decor. Soft '
                                 'natural light from the side window creates a clean, warm, and airy feel. Use a '
                                 'shallow depth of field with a slightly blurred background while keeping the pillow '
                                 'sharp and detailed. Highlight the fabric texture, embroidery, stitching, edging, and '
                                 'handcrafted finish. \n'
                                 '\n'
                                 'IMPORTANT: Maintain EXACTLY the shape, fabric texture, color palette, edging '
                                 'details, stitching, embroidery texture, proportions, and handcrafted look of the '
                                 'pillow from the reference image. Do not redesign, redraw, distort, or alter the '
                                 'pillow. Only create a bedroom backdrop and decorative style around the pillow. \n'
                                 '\n'
                                 'STYLE: Authentic handcrafted product photography, Etsy lifestyle photos, cozy '
                                 'bedroom with neutral tones, soft natural light from the window, high-end handcrafted '
                                 'pillow, warm minimalist home decor, shallow depth of field, 1:1 square aspect '
                                 'ratio. \n'
                                 '\n'
                                 'AVOID: altering the pillow design, specific embroidery patterns, harsh studio '
                                 'lighting, cluttered backgrounds, plastic-looking fabric, flat machine embroidery, '
                                 'blurry pillow details, mass-produced appearance, AI errors, text overlays, logos, '
                                 'watermarks.'),
                                ('Product display',
                                 '2 gối cạnh nhau',
                                 'Use the two pillows in the reference photo as the main product. Create an authentic '
                                 'Etsy-style product photo showcasing the two pillows neatly arranged on a '
                                 'light-colored sofa in a bright living room. Decorate the scene with minimalist '
                                 'cream-colored furniture, soft window curtains, a vase of fresh flowers, and light, '
                                 'romantic decorative items. Use a shallow depth of field with a slightly blurred '
                                 'background while keeping the pillows sharp and detailed. \n'
                                 '\n'
                                 'IMPORTANT: Keep the pillow shape, material, color palette, embroidery placement, '
                                 'proportions, and handcrafted look of the pillows EXACTLY as in the reference photo. '
                                 'Do not redesign, repaint, distort, or alter the pillows. Only create the background '
                                 'and decorate the living room around the pillows. \n'
                                 '\n'
                                 'STYLE: Authentic handcrafted product photography, Etsy-style lifestyle photos, cozy '
                                 'and romantic home decor, soft natural light from windows, pastel color palette, '
                                 'high-end personalized pillows, shallow depth of field, 1:1 square aspect ratio. \n'
                                 '\n'
                                 'AVOID: altering pillow shapes, inaccurate embroidered names or lettering, overly '
                                 'harsh studio lighting, cluttered backgrounds, plastic-looking fabrics, flat machine '
                                 'embroidery, blurry pillow details, distorted heart shapes, mass-produced appearance, '
                                 'AI errors, text overlays, logos, watermarks.'),
                                ('Product display',
                                 '4 gối stack dọc',
                                 'Use the four pillows in the reference photo as the main product. Create an authentic '
                                 'Etsy-style product photo, showcasing three neatly arranged handmade pillows on a '
                                 'light-colored wooden bench, with one standing upright to highlight the embroidery. '
                                 'Use a clean cream or white background with minimalist decor to accentuate the colors '
                                 'and textures. \n'
                                 '\n'
                                 'IMPORTANT: Maintain the pillow shape, color palette, embroidery placement, '
                                 'proportions, and handcrafted look as in the reference photo. Do not redesign, '
                                 'redraw, distort, or alter the pillows. Only improve the background, lighting, and '
                                 'product style. \n'
                                 '\n'
                                 'STYLE: Authentic handcrafted product photography, Etsy editorial style product '
                                 'photo, soft natural light from a window, cozy cottage style, minimalist background, '
                                 'high-quality handmade pillows, 1:1 square aspect ratio. \n'
                                 '\n'
                                 'AVOID: changing colors. Altering pillows, embroidery designs, or specific embroidery '
                                 'patterns. Example: Harsh studio lighting, cluttered background, flat machine '
                                 'embroidery, blurry fabric details, distorted folded edges, mass-produced appearance, '
                                 'AI errors, text overlays, logos, watermarks.'),
                                ('Product display',
                                 '3 gối 3 màu',
                                 'Using three pillows as shown in the reference image as the main product, three '
                                 'pillows in three different colors (but with the same embroidery style, the same '
                                 'color of eyelet embroidery thread, and different pillowcase colors), arrange them '
                                 'neatly on a white crib or baby bed, one in the crib, one on the bed. Decorate the '
                                 'scene with clean white bedding, soft cloud-shaped pillows in the background, and a '
                                 'bright, minimalist nursery space. Keep the layout clean, focusing on the product. \n'
                                 '\n'
                                 'IMPORTANT: Maintain the pillow shape, fabric, color palette, embroidery placement, '
                                 'proportions, and handcrafted look from the reference image. Do not redesign, '
                                 'repaint, distort, or alter the pillows. Only improve the nursery background, '
                                 'lighting, and product style. \n'
                                 '\n'
                                 'STYLE: Authentic handcrafted product photos, Etsy-style editorial product photos, '
                                 'soft natural light from the window, bright white nursery, cozy nursery aesthetics, '
                                 'high-end personalized pillows, backdrop. Minimalist, clean, balanced. 1:1 square '
                                 'ratio. \n'
                                 '\n'
                                 'AVOID: changing pillow colors, changing pillow shapes, embroidering specific names, '
                                 'harsh studio lighting, cluttered backdrops, blurred or distorted fabric details, '
                                 'flat machine embroidery, mass-produced patterns, AI errors, text overlays, logos, '
                                 'watermarks.'),
                                ('Cận thêu tay',
                                 'Cận thêu — collage',
                                 'Use the pillow in the reference image as the main product. Create a detailed collage '
                                 'in the Etsy style, showcasing the handcrafted pillow up close. Arrange the images '
                                 'into four neat frames with minimal white borders, similar to a high-end product '
                                 'detail sheet. Each small image shows a close-up of the raised embroidery on the '
                                 'pillow from different angles. \n'
                                 '\n'
                                 'IMPORTANT: Maintain the EXACT pillow shape, fabric material, color palette, '
                                 'embroidery placement, border or ruffle details, stitching, proportions, and '
                                 'handcrafted look from the reference image. Do not redesign, redraw, distort, or '
                                 'alter the pillow. Only improve the close-up composition, lighting, and product '
                                 'photography style. \n'
                                 '\n'
                                 'STYLE: Authentic handcrafted product photos, detailed collage in the Etsy editorial '
                                 'style, soft natural light from a window, neutral linen background, close-up of '
                                 'fabric texture, raised embroidery, high-end handcrafted pillow, 1:1 square aspect '
                                 'ratio. \n'
                                 '\n'
                                 'AVOID: changing the pillow design, altering colors, harsh lighting, distracting '
                                 'backgrounds, blurry stitching, fabric that looks like plastic, flat machine '
                                 'embroidery, distorted pillow shape, AI errors, text overlaying images, logos, and '
                                 'watermarks.'),
                                ('Product display',
                                 'Bé nằm trên gối',
                                 'Use the pillow in the reference photo as the main product. Create an authentic '
                                 'Etsy-style product photo showing a baby comfortably lying on a soft bed or sofa, '
                                 'gently hugging the pillow and sleeping, with the pillow as the focal point of the '
                                 'photo. Use a shallow depth of field so the baby and pillow are in focus while the '
                                 'background texture is slightly blurred. Highlight the fabric, soft stuffing, '
                                 'embroidery, stitching, and the handcrafted look of the pillow. \n'
                                 '\n'
                                 'IMPORTANT: Keep the shape, fabric texture, color palette, embroidery placement, '
                                 'proportions, and handcrafted look of the pillow from the reference photo. Do not '
                                 'redesign, redraw, distort, or alter the pillow. Only create the context and style of '
                                 'the photo showing the baby hugging the pillow. \n'
                                 '\n'
                                 'STYLE: Authentic handcrafted product photography, Etsy lifestyle, soft natural light '
                                 "from a window, baby's room or living room, warm neutral tones, high-quality "
                                 'handcrafted pillow, shallow depth of field. Shallow, 1:1 square aspect ratio. \n'
                                 '\n'
                                 'AVOID: pillow design editing, special embroidery, harsh studio lighting, cluttered '
                                 'background, distorted baby body images, added fingers, blurry pillow details, '
                                 'plastic-looking fabric, mass-produced appearance, AI errors, text overlays, logos, '
                                 'watermarks.'),
                                ('Product display',
                                 'Gối trên bàn/bề mặt + props',
                                 'Use the pillowcases from the reference image as the main product. Create an '
                                 'authentic Etsy-style product photo showcasing three handmade pillowcases in three '
                                 'different colors (three different pillowcase colors but the same yarn color and '
                                 'embroidery pattern), neatly arranged on a clean sofa. Arrange them side-by-side so '
                                 'that all three pillowcases are clearly visible.\n'
                                 '\n'
                                 'Keep the scene bright, clean, and minimalist. Use soft natural light from the side '
                                 'or a nearby window. The background should be simple and beautifully decorated.\n'
                                 '\n'
                                 'IMPORTANT: Maintain the EXACT shape, fabric, color palette, embroidery placement, '
                                 'proportions, and handmade look of the pillowcases from the reference image. Do not '
                                 'redesign, redraw, distort, or alter the product. Simply create a white table layout, '
                                 'lighting, and display the product around it.\n'
                                 '\n'
                                 'STYLE: Authentic handmade product photo, editorial style product photo Etsy, soft '
                                 'natural light from the window. Notebook, dark layout. Simple white desk, '
                                 'high-quality handmade pillowcase, 1:1 square aspect ratio.\n'
                                 '\n'
                                 'AVOID: changing pillowcase design, harsh studio lighting, cluttered background, '
                                 'blurred or distorted fabric details, flat machine embroidery, mass-produced images, '
                                 'AI errors, text overlays, logos, watermarks.'),
                                ('Quy trình',
                                 'Quy trình thêu',
                                 'Use the pillowcase from the reference image as the main product. Create an '
                                 'Etsy-style photo of the crafting process, showing a woman sitting at a table and '
                                 'carefully embroidering with a wool embroidery needle (wooden-handled wool embroidery '
                                 "needle, 1 large, sharp needle, with the yarn at the tip matching the needle's "
                                 'position), a pattern onto fabric in the same color as the pillowcase on the '
                                 "embroidery frame. Focus on the woman's hands, the embroidery frame or fabric area, "
                                 'the embroidery tools, the yarn, and the front of the pillowcase, keeping the product '
                                 'the main subject. Set the scene in a comfortable, handcrafted workspace with a '
                                 'wooden table, soft natural light from a window, and a backdrop of embroidery '
                                 'threads, scissors, and a few simple sewing tools nearby. Keep the scene clean, '
                                 'bright, and slightly dark. Highlight the fabric texture, stitching, embroidery '
                                 'texture, and the handcrafted quality of the pillowcase, marking the exact embroidery '
                                 'locations as in the reference image—just make sure to mark precisely. Color. \n'
                                 '\n'
                                 'IMPORTANT: Maintain the EXACT image. The shape, fabric texture, color palette, '
                                 'embroidery lines... The position, proportions, and handcrafted look of the '
                                 'pillowcase are taken from the reference image. Do not redesign, redraw, distort, or '
                                 'alter the pillowcase. The background and style should focus solely on the woman '
                                 'embroidering. \n'
                                 '\n'
                                 'STYLE: Authentic handcrafted product photography. Etsy-style editing process, soft '
                                 'natural light from a window. Window, cozy craft room space, minimalist style, '
                                 'high-end handcrafted pillowcase, shallow depth of field, 1:1 square aspect ratio. \n'
                                 '\n'
                                 'AVOID: altering the pillowcase design, harsh studio lighting, cluttered background, '
                                 'blurry embroidery details, distorted hands, added fingers, unrealistic needle '
                                 'placement, flat machine embroidery, mass-produced look, AI errors, text overlays, '
                                 'logos, watermarks.'),
                                ('Product display',
                                 'Standalone đơn #2',
                                 'Use the pillow in the reference image as the main product. Create an authentic '
                                 'Etsy-style product photo showcasing a handcrafted decorative pillow neatly placed on '
                                 'a cozy armchair in a bright living room. Decorate the scene with a neutral-colored '
                                 'upholstered chair, soft window lighting, a small wooden table, books, a ceramic mug, '
                                 'a potted plant, and minimalist home decor.\n'
                                 '\n'
                                 'IMPORTANT: Maintain EXACTLY the pillow shape, fabric texture, color palette, '
                                 'embroidery placement, proportions, stitching, and handcrafted look from the '
                                 'reference image. Do not redesign, redraw, distort, or alter the pillow. Only create '
                                 'the living room setting, lighting, and decorations around the pillow.\n'
                                 '\n'
                                 'STYLE: Authentic handcrafted product photography, Etsy-style lifestyle photos, cozy '
                                 'living room with neutral tones, soft natural light from the window, high-quality '
                                 'handcrafted pillows, warm minimalist home decor, shallow depth of field, 1:1 square '
                                 'aspect ratio.\n'
                                 '\n'
                                 'AVOID: pillow design alterations, harsh studio lighting, cluttered backgrounds, '
                                 'blurry embroidery, distorted pillow shapes, flat machine embroidery, plastic-looking '
                                 'fabric, mass-produced appearance, AI errors, text overlays, logos, watermarks.'),
                                ('Product display',
                                 '2 gối variant #2',
                                 'Use the two pillows in the reference photo as the main product. Create an authentic '
                                 'Etsy-style product photo showing two 3-year-old children comfortably seated on a '
                                 'soft bed or sofa, each gently holding a pillow (two pillows of different colors but '
                                 'with the same embroidery pattern). The two pillows should be the focal point of the '
                                 'photo. Use a shallow depth of field so the children and pillows are in focus while '
                                 'the background texture is slightly blurred. Highlight the fabric, soft stuffing, '
                                 'embroidery, stitching, and handcrafted look of the pillows.\n'
                                 '\n'
                                 'IMPORTANT: Keep the shape, fabric texture, color palette, embroidery placement, '
                                 'proportions, and handcrafted look of the pillows from the reference photo. Do not '
                                 'redesign, redraw, distort, or alter the pillows. Only create the context and style '
                                 'of the photo showing the children holding the pillows.\n'
                                 '\n'
                                 'STYLE: Handcrafted product photography. Authentic, lifestyle-inspired. Etsy, light. '
                                 "Gentle natural light from the window, a children's room. Bedroom. Or a cozy living "
                                 'room, warm neutral tones. High-quality handcrafted pillows, shallow depth of field, '
                                 '1:1 square aspect ratio.\n'
                                 '\n'
                                 'AVOID: pillow design editing, special embroidery, harsh studio lighting, cluttered '
                                 'background, distorted baby body images, added fingers, blurry pillow details, '
                                 'plastic-looking fabric, mass-produced appearance, AI errors, text overlays, logos, '
                                 'watermarks.'),
                                ('Gift box',
                                 'Gift box',
                                 'A beautifully wrapped pillowcase is placed in an open paper gift box, highlighting '
                                 "the delicate hand-embroidered pattern. The pillowcase is neatly folded (because it's "
                                 'a pillowcase, it will flatten and not puff up like a regular pillow), the embroidery '
                                 'stands out, and the material is soft and elegant. The background is minimalist and '
                                 'bright with natural light. Focus on the pillowcase. \n'
                                 '\n'
                                 'IMPORTANT: Do not alter the design of the pillowcase or the embroidery. Focus on how '
                                 'the pillowcase is presented in the gift box. Keep the embroidery clearly visible '
                                 'through the packaging. Highlight the material and the neat folding of the '
                                 'pillowcase. Natural light, a bright and clean layout. \n'
                                 '\n'
                                 'STYLE: Present the gift elegantly, with a minimalist aesthetic, soft natural light, '
                                 'subtle sheen to highlight the material, and a neutral background to highlight the '
                                 'gift box and embroidery. Close-up and medium shots show the details of the wrapping '
                                 'paper and embroidery. \n'
                                 '\n'
                                 'AVOID: Leaving the pillowcase exposed. box. Avoid cluttered backgrounds, harsh '
                                 'shadows, or artificial props that distract attention from the gift presentation. Do '
                                 'not distort the embroidery or the shape of the pillowcase.'))},
 'wedding_pillowcase': {'display_name': 'Wedding Pillowcase',
                        'aliases': ('Wedding Pillowcase',
                                    'wedding pillowcase',
                                    'wedding pillow',
                                    'bride groom pillow',
                                    'bride and groom pillow',
                                    'gối cưới',
                                    'goi cuoi',
                                    'vỏ gối cưới',
                                    'vo goi cuoi'),
                        'lock': 'the main product must remain the same wedding pillowcase/cushion with the exact '
                                'pillow shape, fabric surface, embroidered wedding lettering or motif placement, soft '
                                'volume, seam/edge finish, and romantic keepsake scale from the source image',
                        'shots': (('Lifestyle',
                                   'Cô dâu ôm/cầm gối',
                                   'Use the pillow in the reference image as the main product. Create a realistic '
                                   'product photo depicting everyday life, showing the bride comfortably seated in the '
                                   'bridal room (face not visible, only from the nose down), holding the handcrafted '
                                   'decorative pillow as in the reference image, placed on her lap. The pillow should '
                                   'be the focal point of the photo, highlighting the fabric, the raised hand '
                                   'embroidery details, and the high-end finish of the handcrafted product. Soft '
                                   'natural light from a nearby window creates a bright, airy, and natural feel. Use a '
                                   'shallow depth of field to highlight the pillow while maintaining the gentle '
                                   'authenticity of the bride and the bridal room.\n'
                                   '\n'
                                   'IMPORTANT: Maintain the shape, fabric, color palette, raised embroidery texture, '
                                   'proportions, and handcrafted look of the pillow from the reference image. Do not '
                                   'redesign, redraw, distort, or alter the pillow. Do not add specific embroidery '
                                   'patterns. The embroidery pattern must maintain its overall quality and versatility '
                                   'for all applications. Design Pillow. Only use as a backdrop. The scenery and '
                                   'lifestyle surrounding the person holding the pillow.\n'
                                   '\n'
                                   'STYLE: Authentic. Handmade product photos. Lifestyle photos edited in the Etsy '
                                   'style. Homes. Beautiful interior spaces, soft natural light from windows, wedding '
                                   'rooms with neutral tones, shallow depth of field, high-end handmade pillows, '
                                   'raised embroidery, 1:1 square aspect ratio.\n'
                                   '\n'
                                   'AVOID: altering pillow design, oversized embroidery, embroidering specific '
                                   'characters or names, harsh studio lighting, cluttered backgrounds, plastic-looking '
                                   'fabric, flat machine embroidery, distorted hands, added fingers, blurry pillow '
                                   'details, mass-produced look, AI errors, text overlays, logos, watermarks.'),
                                  ('Product display',
                                   'Hero — gối trên giường',
                                   'Use the pillow in the reference photo as the main product. Create an authentic '
                                   'Etsy-style product photo showcasing the handcrafted decorative pillow neatly '
                                   'placed on the wedding bed in a bright, neutral bedroom. The pillow should be the '
                                   'focal point, complemented by soft white bedding, neutral-colored linen pillows, a '
                                   'light-colored headboard, bedside lamp, a large wedding bouquet resting on the '
                                   'bedside table, and minimalist wedding decorations. Soft natural light from the '
                                   'side window creates a clean, warm, and airy feel. Use a shallow depth of field '
                                   'with a slightly blurred background while keeping the pillow sharp and detailed. '
                                   'Highlight the fabric texture, embroidery, stitching, edging, and handcrafted '
                                   'finish. \n'
                                   '\n'
                                   'IMPORTANT: Keep the shape, fabric texture, color palette, stitching, embroidery '
                                   'texture, proportions, and handcrafted look of the pillow from the reference photo. '
                                   'Do not redesign, redraw, distort, or alter the pillow. Only create the bedroom '
                                   'background and Surrounding decorations. The pillow. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photography, Etsy lifestyle photos, wedding '
                                   'room with neutral tones, soft natural light from the window, high-end handcrafted '
                                   'pillows, minimalist home decor, shallow depth of field, 1:1 square aspect ratio. \n'
                                   '\n'
                                   'AVOID: Pillow design editing, specific embroidery patterns, harsh studio lighting, '
                                   'cluttered backgrounds, plastic-looking fabrics, flat machine embroidery, blurry '
                                   'pillow details, mass-produced look, AI errors, text overlays, logos, watermarks.'),
                                  ('Product display',
                                   '2 gối — Bride & Groom',
                                   'Use the two pillows in the reference photo as the main product. Create an '
                                   'authentic Etsy-style product photo showcasing the two pillows neatly arranged on a '
                                   'light-colored sofa in a bright living room. Decorate the scene with minimalist '
                                   'cream-colored furniture, soft window curtains, and light, romantic wedding '
                                   'decorations. Use a shallow depth of field with a slightly blurred background while '
                                   'keeping the pillows sharp and detailed. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the shape, material, color palette, embroidery placement, '
                                   'proportions, and handcrafted look of the pillows as in the reference photo. Do not '
                                   'redesign, repaint, distort, or alter the pillows. Only create the background and '
                                   'decorate the living room around the pillows. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photography, Etsy lifestyle photo, romantic '
                                   'home decor, soft natural light from the window, pastel color palette, highly '
                                   'personalized pillows, shallow depth of field, shallow angle, proportions. 1:1 '
                                   'square. \n'
                                   '\n'
                                   'AVOID: altering the pillow shape, the exact name or lettering embroidered, overly '
                                   'harsh studio lighting, cluttered layout, plastic-like material, flat machine '
                                   'embroidery, blurry pillow details, distorted heart shape, mass-produced '
                                   'appearance, AI errors, text overlays, logos, watermarks.'),
                                  ('Product display',
                                   '4 gối stack dọc',
                                   'Use the four pillows in the reference photo as the main product. Create an '
                                   'authentic Etsy-style product photo, showcasing three neatly arranged handmade '
                                   'pillows on a light-colored wooden bench, with one standing upright to highlight '
                                   'the embroidery. Use a clean cream or white background with minimalist decor to '
                                   'accentuate the colors and textures. \n'
                                   '\n'
                                   'IMPORTANT: Keep the pillow shape, color palette, embroidery placement, '
                                   'proportions, and handcrafted look as in the reference photo. Do not redesign, '
                                   'redraw, distort, or alter the pillows. Only improve the background, lighting, and '
                                   'product style. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photography, Etsy editorial style product '
                                   'photo, soft natural light from a window, cozy cottage style, minimalist '
                                   'background, high-quality handmade pillows, 1:1 square aspect ratio. \n'
                                   '\n'
                                   'AVOID: changing colors. Changing pillows, embroidery designs, or embroidery '
                                   'patterns. Specifically. For example: Harsh studio lighting, cluttered background, '
                                   'flat machine embroidery, blurry fabric details, distorted folded edges, '
                                   'mass-produced appearance, AI errors, text overlays, logos, watermarks.'),
                                  ('Product display',
                                   '3 gối 3 màu',
                                   'Using three pillows as shown in the reference image but in different colors as the '
                                   'main product, three pillows with three different colors (but with the same '
                                   'embroidery style, same thread color, and unique embroidery name), arrange them '
                                   'neatly on a white crib or baby bed, one in the crib, one on the bed. Decorate the '
                                   'scene with clean white bedding, soft cloud-shaped pillows, and a bright, '
                                   'minimalist nursery space. Keep the layout neat, focusing on the product. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the pillow shape, fabric material, color palette, embroidery '
                                   'placement, proportions, and handcrafted look from the reference image. Do not '
                                   'redesign, repaint, distort, or alter the pillows. Only improve the nursery space, '
                                   'lighting, and product style. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photos, Etsy editorial style product photos, '
                                   'soft natural light from the window, bright white nursery room, nursery aesthetics, '
                                   'pillow-shaped pillows. Fish. Premium, personalized backdrop. Minimalist, clean, '
                                   'balanced. 1:1 ratio. \n'
                                   '\n'
                                   'AVOID: changing pillow colors, changing pillow shapes, embroidery. Specific names, '
                                   'harsh studio lighting, cluttered backdrops, blurred or distorted fabric details, '
                                   'warped edges, flat machine embroidery, mass-produced patterns, AI errors, text '
                                   'overlays, logos, watermarks.'),
                                  ('Cận thêu tay',
                                   'Cận thêu — collage',
                                   'Use the pillow in the reference image as the main product. Create a detailed '
                                   'collage in the Etsy style, showcasing the handcrafted pillow up close. Arrange the '
                                   'images into four neat frames with minimal white borders, similar to a high-end '
                                   'product detail sheet. Each small image shows a close-up of the raised embroidery '
                                   'on the pillow from different angles. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT pillow shape, fabric material, color palette, '
                                   'embroidery placement, border or ruffle details, stitching, proportions, and '
                                   'handcrafted look from the reference image. Do not redesign, redraw, distort, or '
                                   'alter the pillow. Only improve the close-up composition, lighting, and product '
                                   'photography style. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photos, detailed collage in the Etsy '
                                   'editorial style, soft natural light from a window, neutral linen background, '
                                   'close-up of fabric texture, raised embroidery, high-end handcrafted pillow, 1:1 '
                                   'square aspect ratio. \n'
                                   '\n'
                                   'AVOID: changing the pillow design, altering colors, harsh lighting, distracting '
                                   'backgrounds, blurry stitching, fabric that looks like plastic, flat machine '
                                   'embroidery, distorted pillow shape, AI errors, text overlaying images, logos, and '
                                   'watermarks.'),
                                  ('Product display',
                                   'Standalone đơn',
                                   'Use the pillows from the reference image as the main product. Create an authentic '
                                   'Etsy-style product photo, showing a pillow, just like in the reference image, '
                                   'placed on a windowsill. Decorate the scene with soft natural light from the '
                                   'window, pastel-colored walls, linen curtains, a large wedding bouquet, books, '
                                   'candles, and minimalist, light wedding home decor. Keep the pillows in the center '
                                   'and easily visible. The background should feel airy, romantic, and elegant, '
                                   'matching the Etsy product image. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the pillow shape, fabric, color palette, embroidery placement, '
                                   'proportions, and handcrafted look from the reference image. Do not redesign, '
                                   'redraw, distort, or alter the pillows. Create a background for the windowsill, '
                                   'lighting, and decorations surrounding the pillows. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photography, Etsy lifestyle photo, airy '
                                   'window scene, and Bright, soft, natural golden sunlight, minimalist home decor, '
                                   'high-end personalization. Pillows, shallow depth of field, 1:1 square aspect '
                                   'ratio. \n'
                                   '\n'
                                   'AVOID: changing pillow colors, changing pillow shapes, embroidering specific '
                                   'details. Names, overly harsh studio lighting, cluttered backgrounds, blurry '
                                   'embroidery, distorted borders, flat machine embroidery, mass-produced appearance, '
                                   'AI errors, overlapping text, logos, watermarks.'),
                                  ('Lifestyle',
                                   'Đôi uyên ương trên giường',
                                   'Use the pillow in the reference photo as the main product. Create an authentic '
                                   'Etsy-style product photo showing the bride and groom comfortably seated on a soft '
                                   "bed or sofa, gently holding the pillow in both hands. Don't capture the entire "
                                   'face of the bride and groom; only photograph from the nose down, and the pillow '
                                   'should be the focal point of the photo. Use a shallow depth of field so the bride, '
                                   'groom, and pillow are in focus while the background texture is slightly blurred. '
                                   'Highlight the fabric, soft stuffing, embroidery, stitching, and handcrafted look '
                                   'of the pillow. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the shape, fabric texture, color palette, embroidery '
                                   'placement, proportions, and handcrafted look of the pillow from the reference '
                                   'photo. Do not redesign, redraw, distort, or alter the pillow. Only create the '
                                   'context and style of the photo showing the bride and groom holding the pillow. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photography, Etsy lifestyle, natural '
                                   'lighting. Gentle breeze from the window, wedding room. Or a cozy wedding room, '
                                   'warm neutral tones, high-quality handcrafted pillows, shallow depth of field, 1:1 '
                                   'square aspect ratio. \n'
                                   '\n'
                                   'AVOID: pillow design editing, special embroidery, harsh studio lighting, cluttered '
                                   'background, distorted baby body images, added fingers, blurry pillow details, '
                                   'plastic-looking fabric, mass-produced appearance, AI errors, text overlays, logos, '
                                   'watermarks.'),
                                  ('Product display',
                                   '3 gối tổng hợp',
                                   'Use the pillowcases from the reference image as the main product. Create an '
                                   'authentic Etsy-style product photo showcasing three handmade pillowcases in three '
                                   'different colors (each with a different pair of embroidered names), neatly '
                                   'arranged on a clean, soft sofa, complemented by a large, beautiful, and modern '
                                   'wedding bouquet. Arrange them side-by-side so that all three pillowcases are '
                                   'clearly visible.\n'
                                   '\n'
                                   'Keep the scene bright, clean, and minimalist. Use soft natural light from the side '
                                   'or a nearby window. The background should be simple and beautifully decorated.\n'
                                   '\n'
                                   'IMPORTANT: Maintain the EXACT shape, fabric, color palette, embroidery placement, '
                                   'proportions, and handcrafted look of the pillowcases from the reference image. Do '
                                   'not redesign, redraw, distort, or alter the product. Simply create a white table '
                                   'layout, lighting, and display the product around it.\n'
                                   '\n'
                                   'STYLE: Authentic handmade product photo, photo Etsy-style product, soft natural '
                                   'light. Window light, dark layout. Simple white table, high-quality handmade '
                                   'pillowcases, 1:1 square aspect ratio.\n'
                                   '\n'
                                   'AVOID: altering pillowcase designs, overly bright lighting. Studio lighting, '
                                   'cluttered background, blurry fabric details, distorted shapes, flat machine '
                                   'embroidery, mass-produced images, AI errors, text overlays, logos, watermarks.'),
                                  ('Quy trình',
                                   'Quy trình thêu',
                                   'Use the pillowcase from the reference image as the main product. Create an '
                                   'Etsy-style photo of the crafting process, showing a woman sitting at a table '
                                   'carefully embroidering a pattern onto fabric the same color as the pillowcase '
                                   'using a wool embroidery needle (a wooden-handled wool embroidery needle, one '
                                   "large, sharp needle, with the yarn at the tip matching the needle's position). "
                                   "Focus on the woman's hands, the embroidery frame or fabric area, the embroidery "
                                   'tools, the yarn, and the front of the pillowcase, keeping the product the main '
                                   'subject. Set the scene in a comfortable, handcrafted workspace with a wooden '
                                   'table, soft natural light from a window, and a backdrop of embroidery threads, '
                                   'scissors, and a few simple sewing tools nearby. Keep the scene clean and bright. '
                                   'Highlight the fabric texture, stitching, embroidery texture, and the handcrafted '
                                   'quality of the pillowcase, marking the correct embroidery placement as in the '
                                   'reference image, just make sure to use the correct colors. \n'
                                   'QUAN IMPORTANT: Maintain the image EXACTLY. Shape, fabric, color palette, '
                                   'embroidery placement, proportions, and... The illustrative image of the '
                                   'handcrafted style of the pillowcase is taken from a reference image. Do not '
                                   'redesign, redraw, distort, or alter the pillowcase. The background and style '
                                   'should focus solely on the woman embroidering. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photography. Editing process in the style of '
                                   'Etsy, soft natural light from a window. Window, cozy craft room space, minimalist '
                                   'style, high-end handcrafted pillowcase, shallow depth of field, 1:1 square aspect '
                                   'ratio. \n'
                                   '\n'
                                   'AVOID: altering the pillowcase design, harsh studio lighting, cluttered '
                                   'background, blurry embroidery details, distorted hands, added fingers, unrealistic '
                                   'needle placement, flat machine embroidery, mass-produced look, AI errors, text '
                                   'overlays, logos, watermarks.'),
                                  ('Product display',
                                   'Standalone #2',
                                   'Use the pillow in the reference photo as the main product. Create an authentic '
                                   'Etsy-style product photo showcasing a handcrafted decorative pillow neatly placed '
                                   'on a wedding chair in an outdoor wedding setting. Decorate the wedding scene with '
                                   'a wedding table, soft lighting, a small wooden table, flowers, wedding '
                                   'invitations, a large wedding bouquet, and minimalist home decor. \n'
                                   '\n'
                                   'IMPORTANT: Maintain the exact pillow shape, fabric, color palette, embroidery '
                                   'placement, proportions, stitching, and handcrafted look as in the reference photo. '
                                   'Do not redesign, redraw, distort, or alter the pillow. Only create the outdoor '
                                   'wedding setting, lighting, and decorations around the pillow. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photography, Etsy lifestyle photo, bright '
                                   'wedding setting, soft natural lighting, high-quality handcrafted pillow, shallow '
                                   'depth of field. 1:1 square aspect ratio. \n'
                                   '\n'
                                   'AVOID: altering the pillow design, lighting Harsh studio lighting, messy '
                                   'background, blurry embroidery, distorted pillow shape, flat machine embroidery, '
                                   'plastic-like material, mass production. Appearance, AI errors, text overlay, logo, '
                                   'watermark.'),
                                  ('Product display',
                                   '2 bé nằm trên 2 gối',
                                   'Use the two pillows in the reference image as the main product. Create an '
                                   'authentic Etsy-style product photo showing two babies comfortably seated on a soft '
                                   'bed or sofa, each gently holding a pillow with both hands (two pillows of '
                                   "different colors but with the same embroidery). Do not photograph the babies' "
                                   'entire faces, only from the nose down, and the pillows should be the focal point '
                                   'of the photo. Use a shallow depth of field so that the babies and pillows are in '
                                   'focus while the background texture is slightly blurred. Highlight the fabric, soft '
                                   'stuffing, embroidery, stitching, and the handcrafted look of the pillows.\n'
                                   '\n'
                                   'IMPORTANT: Maintain the shape, fabric texture, color palette, embroidery '
                                   'placement, proportions, and handcrafted look of the pillows from the reference '
                                   'image. Do not redesign, redraw, distort, or alter the pillows. Only create the '
                                   'context and style of the photo showing the babies holding the pillows.\n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photography, lifestyle style. Etsy, soft '
                                   "natural light from the window, a child's room. Or a cozy living room, warm neutral "
                                   'tones, high-quality handcrafted pillows, shallow depth of field, 1:1 square aspect '
                                   'ratio.\n'
                                   '\n'
                                   'AVOID: pillow design editing, special embroidery, harsh studio lighting, cluttered '
                                   'background, distorted baby body images, added fingers, blurry pillow details, '
                                   'plastic-looking fabric, mass-produced appearance, AI errors, text overlays, logos, '
                                   'watermarks.'),
                                  ('Product display',
                                   '2 gối realistic',
                                   'Use the pillowcases from the reference image as the main product. Create a '
                                   'realistic Etsy-style product photo showing two embroidered pillowcases, identical '
                                   'to the reference image, neatly placed side-by-side on a clean white bed. The '
                                   'setting should be a bright, modern bedroom with white bedding, a wooden headboard, '
                                   'simple bedside tables, soft pendant lights, and a framed wedding photo above the '
                                   'bed. Soft natural light streams in from the side window, creating a clean, airy, '
                                   'and romantic bedroom atmosphere. Keep the layout focused and minimalist, with the '
                                   'pillowcases clearly displayed as the main focal point. \n'
                                   '\n'
                                   'IMPORTANT: Maintain EXACTLY the shape of the pillowcases, fabric texture, color '
                                   'palette, embroidery placement, proportions, and handcrafted look from the '
                                   'reference image. Do not redesign, redraw, distort, or alter the pillowcases. '
                                   'Simply create a background, lighting, and bedroom decor style that complements the '
                                   'product. \n'
                                   '\n'
                                   'STYLE: Authentic handcrafted product photos, Etsy lifestyle photos, romantic '
                                   'modern bedroom, soft natural light from the window, pristine white bedding, '
                                   'personalized premium pillowcases, minimalist home decor, 1:1 square aspect '
                                   'ratio. \n'
                                   '\n'
                                   'AVOID: altered pillowcase shapes, specific embroidered names, harsh studio '
                                   'lighting, cluttered backgrounds, blurry embroidery, distorted pillows, '
                                   'plastic-like fabric, mass-produced appearance, AI errors, text overlays, logos, '
                                   'watermarks.'),
                                  ('Gift box',
                                   'Gift box — quà cưới',
                                   'A beautifully wrapped pillowcase is placed in an open paper gift box, highlighting '
                                   'the delicate hand-embroidered pattern. The pillowcase is neatly folded, the '
                                   'embroidery stands out, and the material is soft and elegant. The background is '
                                   "minimalist and bright with natural light. Focus on the pillowcase (it's just a "
                                   'pillowcase, so it will flatten, not puff up like the pillow in the picture).\n'
                                   '\n'
                                   'IMPORTANT: Do not alter the design of the pillowcase or the embroidery. Focus on '
                                   'how the pillowcase is presented in the gift box. Keep the embroidery clearly '
                                   'visible through the packaging. Highlight the material and the neat folding of the '
                                   'pillowcase. Natural light, bright and clean layout.\n'
                                   '\n'
                                   'STYLE: Present the gift elegantly, with a minimalist aesthetic, soft natural '
                                   'light, subtle sheen to highlight the material, and a neutral background to '
                                   'highlight the gift box and embroidery. Close-up and medium shots show the details '
                                   'of the wrapping paper and embroidery.\n'
                                   '\n'
                                   'AVOID: Leaving the pillowcase exposed outside the box. Avoid A cluttered '
                                   'background, harsh shadows, or artificial props distract attention from the '
                                   'presentation of the gift. Do not distort the embroidery or the shape of the '
                                   'pillowcase.'))},
 'baby_pillowcase': {'display_name': 'Baby Pillowcase',
                     'aliases': ('Baby Pillowcase',
                                 'baby pillowcase',
                                 'baby pillow',
                                 'nursery pillow',
                                 'children pillow',
                                 'gối em bé',
                                 'goi em be',
                                 'vỏ gối bé',
                                 'vo goi be',
                                 'gối bé',
                                 'goi be'),
                     'lock': 'the main product must remain the same baby/nursery pillowcase or cushion with the exact '
                             'pillow shape, soft volume, fabric weave, embroidered name/motif placement, seam/edge '
                             'finish, color, and baby-safe nursery scale from the source image',
                     'shots': (('Lifestyle',
                                'Mẹ bế bé + gối thêu tên',
                                'Use the pillow in the reference image as the main product. Create a realistic product '
                                'photo depicting everyday life, showing a mother and baby comfortably seated in the '
                                'living room (faces obscured, only noses and lower bodies visible), touching the '
                                'embroidery of the handcrafted decorative pillow as in the reference image. The pillow '
                                'should be the focal point of the photo, highlighting the fabric, the raised '
                                'embroidery details, and the high-quality finish of the handcrafted product. Soft '
                                'natural light from a nearby window creates a bright, airy, and natural feel. Use a '
                                'shallow depth of field to highlight the pillow while maintaining the gentle '
                                'authenticity of the woman and the living room.\n'
                                '\n'
                                'IMPORTANT: Keep the shape, fabric, color palette, embroidery texture, proportions, '
                                'and handcrafted look of the pillow from the reference image. Do not redesign, redraw, '
                                'distort, or alter the pillow. Do not add specific embroidery patterns. The embroidery '
                                'pattern must maintain its overall quality and versatility for all occasions. '
                                'Application. Pillow design. Background only. Landscape and life surrounding the '
                                'person holding the pillow.\n'
                                '\n'
                                'STYLE: Authentic. Handmade product photo. Lifestyle photo. Photo edited in Etsy '
                                'style. Theme: Home. Beautiful interior space, soft natural light from the window, '
                                'living room with neutral tones, shallow depth of field, high-end handmade pillow, '
                                'raised embroidery, 1:1 square aspect ratio.\n'
                                '\n'
                                'AVOID: pillow design editing, oversized embroidery, embroidery of specific characters '
                                'or names, harsh studio lighting, cluttered background, plastic-looking fabric, flat '
                                'machine embroidery, distorted hands, added fingers, blurry pillow details, '
                                'mass-produced look, AI errors, text overlays, logos, watermarks.'),
                               ('Product display',
                                'Hero — gối trên giường nursery',
                                'Use the pillow in the reference image as the main product. Create an authentic '
                                'Etsy-style product photo showcasing the handcrafted decorative pillow neatly placed '
                                'on a cozy bed in a bright, neutral bedroom. The pillow should be the centerpiece, '
                                'complemented by soft white bedding, neutral linen pillows, a light-colored headboard, '
                                'a bedside lamp, small potted plants, and minimalist home decor. Soft natural light '
                                'from the side window creates a clean, warm, and airy feel. Use a shallow depth of '
                                'field with a slightly blurred background while keeping the pillow sharp and detailed. '
                                'Highlight the fabric texture, embroidery, stitching, edging, and handcrafted '
                                'finish. \n'
                                '\n'
                                'IMPORTANT: Maintain EXACTLY the shape, fabric texture, color palette, edging details, '
                                'stitching, embroidery texture, proportions, and handcrafted look of the pillow from '
                                'the reference image. Do not redesign, redraw, distort, or alter the pillow. Only '
                                'create a bedroom backdrop and decorative style around the pillow. \n'
                                '\n'
                                'STYLE: Authentic handcrafted product photography, Etsy lifestyle photos, cozy bedroom '
                                'with neutral tones, soft natural light from the window, high-end handcrafted pillow, '
                                'warm minimalist home decor, shallow depth of field, 1:1 square aspect ratio. \n'
                                '\n'
                                'AVOID: altering the pillow design, specific embroidery patterns, harsh studio '
                                'lighting, cluttered backgrounds, plastic-looking fabric, flat machine embroidery, '
                                'blurry pillow details, mass-produced appearance, AI errors, text overlays, logos, '
                                'watermarks.'),
                               ('Product display',
                                '2 gối cùng màu — khác tên',
                                'Use the two pillows in the reference photo as the main product (two pillows of the '
                                'same color but different names). Create an authentic Etsy-style product photo, '
                                'showcasing the two pillows neatly arranged on a light-colored sofa in a bright living '
                                'room. Decorate the scene with minimalist cream-colored furniture, soft window '
                                'curtains, a vase of fresh flowers, and light, romantic decorative items. Use a '
                                'shallow depth of field with a slightly blurred background while keeping the pillows '
                                'sharp and detailed. \n'
                                '\n'
                                'IMPORTANT: Maintain the exact shape, material, color palette, embroidery placement, '
                                'proportions, and handcrafted look of the pillows as in the reference photo. Do not '
                                'redesign, repaint, distort, or alter the pillows. Only create the background and '
                                'decorate the living room around the pillows. \n'
                                '\n'
                                'STYLE: Authentic handcrafted product photography, Etsy lifestyle photography, cozy '
                                'and romantic home decor, soft natural light from the window, pastel color palette. '
                                'High-end personalized pillow, shallow depth of field, 1:1 square aspect ratio. \n'
                                '\n'
                                'AVOID: altering the pillow shape, inaccurate embroidered name or text, overly harsh '
                                'studio lighting, cluttered layout, plastic-like material, flat machine embroidery, '
                                'blurry pillow details, distorted heart shape, mass-produced appearance, AI errors, '
                                'text overlays, logos, watermarks.'),
                               ('Product display',
                                '4 gối stack dọc',
                                'Use the four pillows in the reference photo as the main product. Create an authentic '
                                'Etsy-style product photo, showcasing three neatly arranged handmade pillows on a '
                                'light-colored wooden bench, with one standing upright to highlight the embroidery. '
                                'Use a clean cream or white background with minimalist decor to accentuate the colors '
                                'and textures. \n'
                                '\n'
                                'IMPORTANT: Maintain the pillow shape, color palette, embroidery placement, '
                                'proportions, and handcrafted look as in the reference photo. Do not redesign, redraw, '
                                'distort, or alter the pillows. Only improve the background, lighting, and product '
                                'style. \n'
                                '\n'
                                'STYLE: Authentic handcrafted product photography, Etsy editorial style product photo, '
                                'soft natural light from a window, cozy cottage style, minimalist background, '
                                'high-quality handmade pillows, 1:1 square aspect ratio. \n'
                                '\n'
                                'AVOID: changing colors. Altering pillows, embroidery designs, or specific embroidery '
                                'patterns. Example: Harsh studio lighting, cluttered background, flat machine '
                                'embroidery, blurry fabric details, distorted folded edges, mass-produced appearance, '
                                'AI errors, text overlays, logos, watermarks.'),
                               ('Product display',
                                '3 gối 3 màu',
                                'Using three pillows as shown in the reference image as the main product, three '
                                'pillows in three different colors (but with the same embroidery style, the same '
                                'embroidery thread color, and different pillowcase colors and different personalized '
                                'names), arrange them neatly on a white crib or baby bed, one in the crib, one on the '
                                'bed. Decorate the scene with pristine white bedding, soft cloud-shaped pillows in the '
                                'background, and a bright, minimalist nursery space. Keep the layout clean, focusing '
                                'on the product. \n'
                                '\n'
                                'IMPORTANT: Maintain the pillow shape, fabric material, color palette, embroidery '
                                'placement, proportions, and handcrafted look from the reference image. Do not '
                                'redesign, repaint, distort, or alter the pillows. Only improve the nursery '
                                'background, lighting, and product style. \n'
                                '\n'
                                'STYLE: Authentic handcrafted product photos, Etsy editorial style product photos, '
                                'soft natural light from the window, bright white nursery room, room aesthetics. Cozy '
                                'newborn, premium personalized pillow, backdrop. Minimalist, clean, balanced. 1:1 '
                                'square ratio. \n'
                                '\n'
                                'AVOID: changing pillow color, changing pillow shape, embroidering specific names, '
                                'harsh studio lighting, cluttered backdrop, blurred or distorted fabric details, flat '
                                'machine embroidery, mass production patterns, AI errors, text overlays, logos, '
                                'watermarks.'),
                               ('Cận thêu tay',
                                'Cận thêu — collage',
                                'Use the pillow in the reference image as the main product. Create a detailed collage '
                                'in the Etsy style, showcasing the handcrafted pillow up close. Arrange the images '
                                'into four neat frames with minimal white borders, similar to a high-end product '
                                'detail sheet. Each small image shows a close-up of the raised embroidery on the '
                                'pillow from different angles. \n'
                                '\n'
                                'IMPORTANT: Maintain the EXACT pillow shape, fabric material, color palette, '
                                'embroidery placement, border or ruffle details, stitching, proportions, and '
                                'handcrafted look from the reference image. Do not redesign, redraw, distort, or alter '
                                'the pillow. Only improve the close-up composition, lighting, and product photography '
                                'style. \n'
                                '\n'
                                'STYLE: Authentic handcrafted product photos, detailed collage in the Etsy editorial '
                                'style, soft natural light from a window, neutral linen background, close-up of fabric '
                                'texture, raised embroidery, high-end handcrafted pillow, 1:1 square aspect ratio. \n'
                                '\n'
                                'AVOID: changing the pillow design, altering colors, harsh lighting, distracting '
                                'backgrounds, blurry stitching, fabric that looks like plastic, flat machine '
                                'embroidery, distorted pillow shape, AI errors, text overlaying images, logos, and '
                                'watermarks.'),
                               ('Product display',
                                'Bé nằm trên gối',
                                'Use the pillow in the reference photo as the main product. Create an authentic '
                                'Etsy-style product photo showing a baby comfortably lying on a soft bed or sofa, '
                                'gently hugging the pillow and sleeping, with the pillow as the focal point of the '
                                'photo. Use a shallow depth of field so the baby and pillow are in focus while the '
                                'background texture is slightly blurred. Highlight the fabric, soft stuffing, '
                                'embroidery, stitching, and the handcrafted look of the pillow. \n'
                                '\n'
                                'IMPORTANT: Keep the shape, fabric texture, color palette, embroidery placement, '
                                'proportions, and handcrafted look of the pillow from the reference photo. Do not '
                                'redesign, redraw, distort, or alter the pillow. Only create the context and style of '
                                'the photo showing the baby hugging the pillow. \n'
                                '\n'
                                'STYLE: Authentic handcrafted product photography, Etsy lifestyle, soft natural light '
                                "from a window, baby's room or living room, warm neutral tones, high-quality "
                                'handcrafted pillow, shallow depth of field. Shallow, 1:1 square aspect ratio. \n'
                                '\n'
                                'AVOID: pillow design editing, special embroidery, harsh studio lighting, cluttered '
                                'background, distorted baby body images, added fingers, blurry pillow details, '
                                'plastic-looking fabric, mass-produced appearance, AI errors, text overlays, logos, '
                                'watermarks.'),
                               ('Product display',
                                '3 gối tổng hợp',
                                'Use the pillowcases from the reference image as the main product. Create an authentic '
                                'Etsy-style product photo showcasing three handmade pillowcases in three different '
                                'colors (three different pillowcase colors, different names, but the same thread color '
                                'and embroidery style), neatly arranged on a clean sofa. Arrange them side-by-side so '
                                'that all three pillowcases are clearly visible (these are pillowcases, not pillows, '
                                "so they shouldn't be too puffy). \n"
                                '\n'
                                'Keep the scene bright, clean, and minimalist. Use soft natural light from the side or '
                                'a nearby window. The background should be simple and beautifully decorated. \n'
                                '\n'
                                'IMPORTANT: Maintain the EXACT shape, fabric, color palette, embroidery placement, '
                                'proportions, and handmade look of the pillowcases from the reference image. Do not '
                                'redesign, redraw, distort, or alter the product. Simply create a white table layout, '
                                'lighting, and display the product around it. \n'
                                '\n'
                                'STYLE: Product Photo Authentic handcrafted. Product photos in Etsy editorial style, '
                                'soft natural light from the window. Notebook, dark layout. Simple white table, '
                                'high-quality handmade pillowcase, 1:1 square aspect ratio. \n'
                                '\n'
                                'AVOID: heavily edited pillowcase designs, overly harsh studio lighting, cluttered '
                                'backgrounds, blurry or distorted fabric details, flat machine embroidery, '
                                'mass-produced images, AI errors, overlapping text, logos, watermarks.'),
                               ('Quy trình',
                                'Quy trình thêu',
                                'Use the pillowcase from the reference image as the main product. Create an Etsy-style '
                                'photo of the crafting process, showing a woman sitting at a table, carefully '
                                'embroidering a pattern onto fabric the same color as the pillowcase using a wool '
                                'embroidery needle (an embroidery needle with a wooden handle, a large, sharp needle '
                                "with the yarn at the tip matching the needle's position) ON A CIRCULAR EMBROIDERY "
                                "FRAME. Focus on the woman's hands, the embroidery frame or fabric area, the "
                                'embroidery tools, the yarn, and the front of the pillowcase, keeping the product the '
                                'main subject. Set the scene in a comfortable, handcrafted workspace with a wooden '
                                'table, soft natural light from a window, and a backdrop of embroidery threads, '
                                'scissors, and a few simple sewing tools nearby. Keep the scene clean and bright. '
                                'Highlight the fabric texture, stitching, embroidery texture, and the quality of the '
                                "pillowcase's craftsmanship, accurately marking the embroidery placement as in the "
                                'reference image, ensuring the correct colors are used. \n'
                                '\n'
                                'IMPORTANT: Maintain the image EXACTLY. Shape, fabric, color palette, embroidery '
                                'placement, proportions, and... Illustrative image. The illustrative image of the '
                                'handmade pillowcase is taken from a reference photo. Do not redesign, redraw, '
                                'distort, or alter the pillowcase. The background and style should focus solely on the '
                                'woman embroidering. \n'
                                '\n'
                                'STYLE: Authentic handmade product photography. Editing process in Etsy style, soft '
                                'natural light from a window. Window, cozy room space with handicrafts, minimalist '
                                'style, high-end handmade pillowcase, shallow depth of field, 1:1 square aspect '
                                'ratio. \n'
                                '\n'
                                'AVOID: altering the pillowcase design, harsh studio lighting, cluttered background, '
                                'blurry embroidery details, distorted hands, added fingers, unrealistic needle '
                                'placement, flat machine embroidery, mass-produced appearance. Mass production, AI '
                                'errors, text overlays, logos, watermarks.'),
                               ('Product display',
                                'Standalone đơn',
                                'Use the pillow in the reference image as the main product. Create an authentic '
                                'Etsy-style product photo showcasing a handcrafted decorative pillow neatly placed on '
                                'a cozy armchair in a bright living room. Decorate the scene with a neutral-colored '
                                'upholstered chair, soft window lighting, a small wooden table, books, a ceramic mug, '
                                'a potted plant, and minimalist home decor.\n'
                                '\n'
                                'IMPORTANT: Maintain EXACTLY the pillow shape, fabric texture, color palette, '
                                'embroidery placement, proportions, stitching, and handcrafted look from the reference '
                                'image. Do not redesign, redraw, distort, or alter the pillow. Only create the living '
                                'room setting, lighting, and decorations around the pillow.\n'
                                '\n'
                                'STYLE: Authentic handcrafted product photography, Etsy-style lifestyle photos, cozy '
                                'living room with neutral tones, soft natural light from the window, high-quality '
                                'handcrafted pillows, warm minimalist home decor, shallow depth of field, 1:1 square '
                                'aspect ratio.\n'
                                '\n'
                                'AVOID: pillow design alterations, harsh studio lighting, cluttered backgrounds, '
                                'blurry embroidery, distorted pillow shapes, flat machine embroidery, plastic-looking '
                                'fabric, mass-produced appearance, AI errors, text overlays, logos, watermarks.'),
                               ('Product display',
                                '2 trẻ nằm — 2 tên khác',
                                'Use the two pillows in the reference photo as the main product. Create an authentic '
                                'Etsy-style product photo showing two 3-year-old children comfortably seated on a soft '
                                'bed or sofa, each gently hugging a pillow (two pillows of different colors and names '
                                'but with the same embroidery pattern and thread color). The two pillows should be the '
                                'focal point of the photo. Use a shallow depth of field so the children and pillows '
                                'are in focus while the background has a slightly blurred texture. Highlight the '
                                'fabric, soft stuffing, embroidery, stitching, and handcrafted look of the pillows.\n'
                                '\n'
                                'IMPORTANT: Maintain the shape, fabric texture, color palette, embroidery placement, '
                                'proportions, and handcrafted look of the pillows from the reference photo. Do not '
                                'redesign, redraw, distort, or alter the pillows. Only create the context and style '
                                'for the photo showing the children hugging the pillows.\n'
                                '\n'
                                'STYLE: Handcrafted product photography. Authentic, inspired by the style. Living. '
                                "Etsy style, light. Soft natural light from the window, children's room. Bedroom. Or a "
                                'cozy living room, warm neutral tones. High-quality handmade pillows. Shallow depth of '
                                'field, 1:1 square aspect ratio.\n'
                                '\n'
                                'AVOID: pillow design editing, special embroidery, harsh studio lighting, cluttered '
                                'background, distorted baby body images, added fingers, blurry pillow details, '
                                'plastic-looking fabric, mass-produced appearance, AI errors, text overlays, logos, '
                                'watermarks.'),
                               ('Gift box',
                                'Gift box — quà sinh nhật',
                                'A beautifully wrapped pillowcase is placed in an open paper gift box, highlighting '
                                "the delicate hand-embroidered design. The pillowcase is neatly folded (because it's a "
                                'pillowcase, it will be flat, not puffy like a regular pillow), the embroidery stands '
                                'out, and the material is soft and elegant. The background is minimalist and bright '
                                'with natural light. Focus on the pillowcase; DO NOT ADD ANYTHING ELSE TO THE '
                                'PILLOWCASE IN THE GIFT BOX TO SHOW THE EMBROIDERY CLEARLY. \n'
                                '\n'
                                'IMPORTANT: Do not alter the design of the pillowcase or the embroidery. Focus on how '
                                'the pillowcase is presented in the gift box. Keep the embroidery clearly visible. '
                                'Highlight the material and the neat folding of the pillowcase. Natural light, a '
                                'bright and clean layout. \n'
                                '\n'
                                'STYLE: Present the gift elegantly, with a minimalist aesthetic, soft natural light, a '
                                'subtle sheen to highlight the material, and the background. Neutral colors are used '
                                'to highlight the gift box and embroidery. Close-up and medium shots show the details '
                                'of the wrapping paper and embroidery. \n'
                                '\n'
                                'AVOID: Showing the pillowcase. Avoid cluttered backgrounds, harsh shadows, or '
                                'artificial props that distract attention from the gift presentation. Do not distort '
                                'the embroidery or the shape of the pillowcase.'))},
 'banner': {'display_name': 'Banner',
            'aliases': ('Banner',
                        'baby banner',
                        'embroidered banner',
                        'wall banner',
                        'wall hanging banner',
                        'nursery banner',
                        'pennant',
                        'pennant banner',
                        'nursery pennant',
                        'embroidered pennant',
                        'baby wall hanging',
                        'wall hanging',
                        'hanging flag',
                        'fabric flag',
                        'linen flag',
                        'cờ vải',
                        'co vai',
                        'cờ treo',
                        'co treo',
                        'lá cờ',
                        'la co',
                        'cờ thêu',
                        'co theu',
                        'cờ trang trí',
                        'co trang tri'),
            'lock': 'the main product must remain the same embroidered baby wall hanging banner/pennant with the exact '
                    'pointed V pennant shape, flat linen fabric panel, top wooden dowel/rod, rope cord hanger, side '
                    'seams, embroidery/name/motif placement, thread color palette, proportions, wall decor scale, and '
                    'premium handmade identity from the source image',
            'shots': (('Lifestyle',
                       'Mẹ và bé chạm vào cờ thêu tên',
                       'Use the embroidered baby wall hanging banner in the reference image as the main product. '
                       'Create a realistic lifestyle product photo showing a mother and baby together in a bright '
                       'nursery, gently touching the embroidered details on the banner. The mother may lightly hold '
                       'the banner or the banner may be hanging low enough for the baby to touch the embroidery. The '
                       'room should feel bright, white, airy, clean, and warm, with soft nursery decor in the '
                       'background.\n'
                       '\n'
                       'IMPORTANT: Maintain the EXACT shape, proportions, linen texture, pointed pennant form, wooden '
                       'rod, rope hanger, embroidery placement, and overall handcrafted look of the banner from the '
                       'reference image. Do not redesign, redraw, distort, or alter the banner itself. Only create a '
                       'new surrounding background and lifestyle scene.\n'
                       '\n'
                       'STYLE: Handmade lifestyle product photography, soft white natural lighting, editorial quality, '
                       'bright airy nursery aesthetic, modern minimalist Etsy style, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: altering the banner design, blurry embroidery, harsh studio lighting, cluttered '
                       'backgrounds, distorted hands, extra fingers, mass-produced look, AI errors, text overlays, '
                       'logos, watermarks.'),
                      ('Product display',
                       'Hero cờ treo trong nursery',
                       'Use the embroidered wall banner for babies shown in the reference image as the main product. '
                       'Create a striking product photo in authentic Etsy style, showcasing a single banner neatly '
                       'hung in a SPACIOUS nursery, positioned above the crib or baby bed. Add soft nursery '
                       'decorations such as teddy bears, folded baby blankets, and light, neutral-colored furniture. '
                       'The room should feel bright, airy, white, and elegant, with the banner as the main focal '
                       'point.\n'
                       '\n'
                       'IMPORTANT: Keep the shape, proportions, linen fabric, pointed flag shape, wooden rod, hanging '
                       'hooks, embroidery placement, and handcrafted look of the banner exactly as in the reference '
                       'image. Do not edit or alter the banner. Only create a new background and style around it.\n'
                       '\n'
                       'STYLE: Handcrafted product photography, soft white natural light, high-quality editing, '
                       'minimalist modern Etsy-style aesthetics, high-end nursery decor style, 1:1 square aspect '
                       'ratio.\n'
                       '\n'
                       'AVOID: Banner design changes, harsh studio lighting, cluttered props, distorted embroidery, '
                       'mass-produced look, AI errors, blurry images, overlays, logos, watermarks.'),
                      ('Product display',
                       '2 cờ cùng kiểu, khác tên, khác màu nền',
                       'Use two embroidered baby wall hanging banners based on the reference image as the main '
                       'products. Create an authentic Etsy-style product photo showing two banners hanging together in '
                       'a bright baby room. Add flavorful wall decor such as small framed photos or simple nursery '
                       'wall art behind them. The two banners must have the exact same shape and embroidery layout as '
                       'the reference image, but with different names and different fabric base colors. The embroidery '
                       'thread colors and style must remain the same as the reference image.\n'
                       '\n'
                       'IMPORTANT: Maintain the EXACT shape, proportions, pointed pennant form, linen texture, wooden '
                       'rod, rope hanger, embroidery placement, and handcrafted look of the banners. Only change the '
                       'names and the fabric base colors. Do not redesign or distort the banners.\n'
                       '\n'
                       'STYLE: Handmade product photography, soft white natural lighting, editorial quality, airy '
                       'nursery wall styling, modern Etsy aesthetic, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: altering the banner design, changing embroidery layout, harsh lighting, cluttered '
                       'walls, distorted banner shapes, blurry embroidery, mass-produced look, AI errors, overlays, '
                       'logos, watermarks.'),
                      ('Product display',
                       '2 cờ đặt trên bàn với đồ em bé',
                       'Use two embroidered baby wall hanging banners based on the reference image as the main '
                       'products. Create a product display photo showing two banners neatly placed on a table in a '
                       'bright airy room. Decorate the table with tasteful baby-related items such as a baby toy, soft '
                       'shoes, a folded baby blanket, or small nursery accessories. The two banners must keep the same '
                       'exact design structure as the reference image, but have different names and different fabric '
                       'base colors. The embroidery thread style and colors must remain the same as the reference '
                       'image.\n'
                       '\n'
                       'IMPORTANT: Maintain the EXACT shape, proportions, pointed pennant form, linen texture, wooden '
                       'rod, rope hanger, embroidery placement, and handcrafted appearance of the banners. Only change '
                       'the names and base fabric colors. Do not redesign or alter the banners themselves.\n'
                       '\n'
                       'STYLE: Handmade product photography, soft white natural lighting, editorial quality, bright '
                       'clean tabletop styling, modern minimalist Etsy aesthetic, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: altering banner design, cluttered props, harsh lighting, distorted product proportions, '
                       'blurry embroidery, mass-produced look, AI errors, overlays, logos, watermarks.'),
                      ('Product display',
                       '3 cờ, 3 màu nền',
                       'Use three embroidered baby wall hanging banners based on the reference image as the main '
                       'products. Create an authentic Etsy-style product photo showing three banners hanging together '
                       'in a bright baby nursery. The three banners should share the same exact style, shape, '
                       'embroidery layout, and handcrafted appearance as the reference image, but each banner should '
                       'have a different name and a different fabric base color. The embroidery style and colors must '
                       'remain the same as the reference image.\n'
                       '\n'
                       'IMPORTANT: Maintain the EXACT shape, proportions, pointed pennant form, linen texture, wooden '
                       'rod, rope hanger, embroidery placement, and handcrafted look of all three banners. Only change '
                       'the names and the fabric base colors. Do not redesign the product.\n'
                       '\n'
                       'STYLE: Handmade product photography, soft white natural lighting, editorial quality, airy '
                       'nursery interior, modern minimalist Etsy style, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: altering the banner design, harsh lighting, cluttered nursery background, distorted '
                       'product shapes, blurry embroidery, mass-produced appearance, AI errors, text overlays, logos, '
                       'watermarks.'),
                      ('Product display',
                       '4 cờ treo cùng nhau',
                       'Use four embroidered baby wall hanging banners based on the reference image as the main '
                       'products. Create an authentic Etsy-style product photo showing four banners hanging together '
                       'in a bright and airy baby room. All four banners must keep the same exact design structure, '
                       'shape, embroidery layout, and handcrafted look as the reference image, but each banner should '
                       'have a different name and a different fabric base color. The embroidery thread style and '
                       'colors must remain unchanged from the reference image.\n'
                       '\n'
                       'IMPORTANT: Maintain the EXACT shape, proportions, pointed pennant form, linen texture, wooden '
                       'rod, rope hanger, embroidery placement, and handcrafted appearance of the banners. Only vary '
                       'the names and base fabric colors. Do not redesign or distort the products.\n'
                       '\n'
                       'STYLE: Handmade product photography, soft white natural lighting, editorial quality, bright '
                       'airy nursery decor, modern Etsy aesthetic, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: altering the banner design, inconsistent embroidery style, harsh studio lighting, '
                       'cluttered background, blurry details, mass-produced look, AI errors, overlays, logos, '
                       'watermarks.'),
                      ('Cận thêu tay',
                       'Collage 4 ảnh nhỏ',
                       'Use the embroidered baby wall hanging banner in the reference image as the main product. '
                       'Create a realistic close-up collage made of four smaller images arranged neatly in one final '
                       'square image. Each panel should show a different close-up angle of the banner, focusing on the '
                       'embroidery texture, linen fabric texture, stitched edges, and handcrafted details. The four '
                       'close-up shots should be bright, sharp, elegant, and premium, like a high-end Etsy detail '
                       'collage.\n'
                       '\n'
                       'IMPORTANT: Maintain the EXACT embroidery texture, linen fabric texture, stitching, banner '
                       'shape, proportions, and handcrafted appearance of the banner from the reference image. Do not '
                       'redesign or alter the product. Only create a refined close-up collage presentation.\n'
                       '\n'
                       'STYLE: Handmade detail photography, close-up editorial collage, soft white natural lighting, '
                       'clean refined Etsy aesthetic, bright and airy presentation, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: blurry close-ups, harsh lighting, cluttered composition, distorted stitches, AI errors, '
                       'overlays, logos, watermarks.'),
                      ('Quy trình',
                       'Người phụ nữ đang thêu cờ',
                       'Use the embroidered baby wall hanging banner in the reference image as the main inspiration '
                       'for the crafting process. Create an Etsy-style process photo showing a woman sitting at a '
                       'clean craft table, carefully embroidering the design onto fabric of the same color as the '
                       'banner. The fabric is stretched in a round embroidery hoop. The needle must be realistically '
                       'placed at the exact point of stitching, and the eye of the needle must clearly contain thread. '
                       'Focus on the embroidery hoop, fabric, needle, thread, and the woman’s careful handwork. The '
                       'overall scene should look clean, bright, airy, and premium handmade.\n'
                       '\n'
                       'IMPORTANT: The needle placement must be realistic and aligned with the current stitch. The '
                       'thread must pass naturally through the needle eye. The embroidery must look genuinely '
                       'handmade, not machine flat. Keep the embroidered design style consistent with the reference '
                       'image.\n'
                       '\n'
                       'STYLE: Hand embroidery process photography, soft white natural lighting, realistic editorial '
                       'Etsy aesthetic, clean craft workspace, premium handmade atmosphere, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: distorted hands, extra fingers, unrealistic needle placement, disconnected thread, flat '
                       'machine-embroidery look, cluttered workspace, harsh studio light, AI errors, overlays, logos, '
                       'watermarks.'),
                      ('Lifestyle',
                       'Mẹ và bé cùng sờ hình thêu',
                       'Use the embroidered baby wall hanging banner in the reference image as the main product. '
                       'Create a lifestyle product photo showing a mother and baby in a bright nursery, both gently '
                       'touching the embroidered details on the banner. The banner may be hanging on the wall or held '
                       'lightly by the mother. The room should feel soft, white, airy, warm, and elegant, with the '
                       'banner clearly visible and the embroidery details easy to see.\n'
                       '\n'
                       'IMPORTANT: Maintain the EXACT shape, proportions, pointed pennant form, linen texture, wooden '
                       'rod, rope hanger, embroidery placement, and handcrafted appearance of the banner from the '
                       'reference image. Do not redesign, distort, or alter the banner itself.\n'
                       '\n'
                       'STYLE: Handmade lifestyle product photography, soft white natural lighting, editorial quality, '
                       'bright airy nursery aesthetic, modern minimalist Etsy style, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: altering the banner design, blurred embroidery, harsh lighting, cluttered background, '
                       'distorted hands, extra fingers, mass-produced look, AI errors, text overlays, logos, '
                       'watermarks.'),
                      ('Product display',
                       '2 bé với 2 cờ, không lộ mặt',
                       'Use two embroidered wall banners for babies based on the reference image as the main product. '
                       'Create a realistic Etsy-style photo showing two babies interacting with the two banners, both '
                       "gently touching the embroidered details. The babies' faces should not be visible; the two "
                       'banners should have different names but maintain the same embroidery style, EMBROIDERY THREAD '
                       'COLOR, layout, and overall design structure as the reference image. The background should feel '
                       'natural, cute, clean, and child-friendly.\n'
                       '\n'
                       'IMPORTANT: Maintain EXACTLY the shape, proportions, flag shape, linen material, wooden frame, '
                       'hanging string, embroidery placement, and handcrafted appearance of the banners from the '
                       'reference image. Only change the names if necessary. Do not redesign or distort the product.\n'
                       '\n'
                       'STYLE: Photograph handcrafted products in a lifestyle style, with soft white natural light, a '
                       "spacious children's room setting, authentic Etsy aesthetics, and a 1:1 square aspect ratio.\n"
                       '\n'
                       'AVOID: Showing the entire face, altering banner design, cluttered styling, harsh lighting, '
                       'distorted hands, adding fingers, blurry embroidery, AI errors, overlays, logos, and '
                       'watermarks.'),
                      ('Product display',
                       'Em bé ngủ, cờ treo gần nôi',
                       'Use the embroidered wall banner for babies shown in the reference image as the main product. '
                       'Create a peaceful Etsy-style photo, showing a baby sleeping in a crib or bassinet, with the '
                       'banner clearly displayed nearby on the wall. The composition should highlight the banner while '
                       "keeping the entire room soft, bright, airy, and tranquil. The children's room should feel "
                       'clean, pristine white, and elegant, with soft lighting.\n'
                       '\n'
                       'IMPORTANT: Maintain EXACTLY the shape, proportions, flag point shape, linen fabric, wooden '
                       'frame, hanging hooks, embroidery placement, and handcrafted appearance of the banner as shown '
                       'in the reference image. Do not redesign or alter the banner itself.\n'
                       '\n'
                       'STYLE: Handcrafted product photography in a lifestyle style, soft white natural lighting, '
                       "peaceful children's room aesthetic, Etsy editorial style, clean and airy composition, 1:1 "
                       'square aspect ratio.\n'
                       '\n'
                       'AVOID: obscuring the banner, harsh lighting, cluttered room decor, blurry embroidery, altered '
                       'design, mass-produced appearance, AI errors, overlays, logos, watermarks.'),
                      ('Gift box -',
                       'Cờ trong hộp quà mở',
                       'Use the embroidered baby wall hanging banner in the reference image as the main product. '
                       'Create a realistic gift presentation photo showing one banner neatly folded inside an open '
                       'paper gift box. Because it is a fabric wall banner, it must look flat and neatly folded, not '
                       'puffed up like a pillow. The embroidery design should remain clearly visible, highlighting the '
                       'fine handcrafted details and elegant linen texture. The scene should be minimal, bright, '
                       'clean, and softly lit with natural white light.\n'
                       '\n'
                       'IMPORTANT: Maintain the EXACT shape, proportions, pointed pennant form, linen texture, '
                       'embroidery placement, wooden rod if visible, rope hanger if visible, and handcrafted '
                       'appearance of the banner from the reference image. Do not redesign, redraw, distort, or alter '
                       'the product itself.\n'
                       '\n'
                       'STYLE: Handmade gift product photography, soft white natural lighting, editorial quality, '
                       'bright minimalist Etsy aesthetic, premium gift presentation, 1:1 square aspect ratio.\n'
                       '\n'
                       'AVOID: making the banner look puffy like a pillow, cluttered gift box styling, harsh lighting, '
                       'distracting objects covering the embroidery, AI errors, overlays, logos, watermarks.'))}}
